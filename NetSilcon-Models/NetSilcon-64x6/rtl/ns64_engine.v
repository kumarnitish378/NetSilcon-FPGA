// =============================================================================
// NetSilcon-64x6 : 16 -> 64 -> 64 -> 64 -> 64 -> 64 -> 64 -> 16 inference engine
//
// 64 MAC lanes, lane j = neuron j of every layer. Each clock ONE input value is
// broadcast to all lanes and each lane adds x * w (its own weight, read from its
// own byte column of the weight RAM). Per layer, with N_in inputs:
//
//   t = 0          read bias low byte   -> acc = bias_lo
//   t = 1          read bias high byte  -> acc += bias_hi * 256
//   t = 2..N_in+1  read weight i = t-2  -> acc += x_i * w_i
//   t = N_in+2, N_in+3   pipeline drain
//   = N_in + 4 clocks per layer
//
// The input stream of layer 1 comes from the 16 input bytes. For layers 2..7,
// at t = 0 all 64 finished sums are copied in one clock into a 64 x 24-bit
// shift chain. The chain shifts one sum per clock into the shared requantizer
// (ReLU, round, shift, clamp), whose output is the input stream x_i of the next
// layer, arriving exactly when weight i is read. After layer 7 the chain feeds
// 16 outputs through the requantizer (signed clamp) into y_out.
//
// Pipeline per word: clock c: address -> c+1: RAM data + x  -> product register
//                    -> c+2: accumulate.  Requantizer: chain head at c -> x at c+2.
//
// Total: (16+4) + 6*(64+4) clocks + 19 for the output = 447 clocks per inference.
// Math is identical to model/ns64.py (bit-exact).
// =============================================================================
module ns64_engine (
    input  wire          clk,
    input  wire          start,         // 1-clock pulse, x_in valid
    input  wire [127:0]  x_in,          // 16 inputs 0..127, x0 in bits 7:0
    input  wire [34:0]   shifts,        // 7 x 5 bits, layer 1 in bits 4:0
    output reg           busy = 1'b0,
    output reg           done = 1'b0,   // 1-clock pulse, y_out valid
    output reg  [127:0]  y_out = 128'd0,// 16 signed outputs, y0 in bits 7:0
    // weight RAM read port (the bank bit is added outside)
    output wire [8:0]    raddr,
    output wire          ram_re,        // weight-RAM read enable (only while computing)
    input  wire [511:0]  rdata
);
    localparam K_NONE = 2'd0, K_LO = 2'd1, K_HI = 2'd2, K_W = 2'd3;

    // ------------------------------------------------------------ sequencer
    reg        run   = 1'b0;            // computing layers 1..7
    reg        outph = 1'b0;            // streaming the 16 outputs
    reg [2:0]  layer = 3'd0;            // 0..6
    reg [6:0]  t     = 7'd0;
    reg [4:0]  oc    = 5'd0;            // output phase clock counter
    reg [127:0] x_reg = 128'd0;

    wire [6:0] n_in = (layer == 3'd0) ? 7'd16 : 7'd64;
    wire [8:0] base = (layer == 3'd0) ? 9'd0   : (layer == 3'd1) ? 9'd18  :   // BASE = [0,18,84,
                      (layer == 3'd2) ? 9'd84  : (layer == 3'd3) ? 9'd150 :   //  150,216,282,348]
                      (layer == 3'd4) ? 9'd216 : (layer == 3'd5) ? 9'd282 : 9'd348;
    assign raddr  = base + {2'b00, t};
    assign ram_re = run;

    wire [1:0] k0 = !run           ? K_NONE :
                    (t == 7'd0)    ? K_LO   :
                    (t == 7'd1)    ? K_HI   :
                    (t < n_in + 7'd2) ? K_W : K_NONE;

    wire layer_end = run && (t == n_in + 7'd3);
    wire chain_load = (run && t == 7'd0 && layer != 3'd0) || (outph && oc == 5'd0);

    always @(posedge clk) begin
        done <= 1'b0;
        if (start && !busy) begin
            busy <= 1'b1; run <= 1'b1; layer <= 3'd0; t <= 7'd0; x_reg <= x_in;
        end else if (run) begin
            if (layer_end) begin
                t <= 7'd0;
                if (layer == 3'd6) begin run <= 1'b0; outph <= 1'b1; oc <= 5'd0; end
                else layer <= layer + 3'd1;
            end else t <= t + 7'd1;
        end else if (outph) begin
            oc <= oc + 5'd1;
            if (oc == 5'd18) begin outph <= 1'b0; busy <= 1'b0; done <= 1'b1; end
        end
    end

    // ------------------------------------------------------------ layer-1 input stream
    reg signed [7:0] x_l1 = 8'sd0;                  // valid one clock after the address
    wire [6:0] wi = t - 7'd2;
    always @(posedge clk) x_l1 <= x_reg[wi[3:0]*8 +: 8];

    // ------------------------------------------------------------ word-kind pipeline
    reg [1:0] k1 = K_NONE, k2 = K_NONE;
    always @(posedge clk) begin k1 <= k0; k2 <= k1; end

    // ------------------------------------------------------------ requantizer + chain
    wire [7:0]  xq;
    wire signed [7:0] x_bus = (layer == 3'd0 && run) ? x_l1 : $signed(xq);

    wire [64*24-1:0] accs;
    reg  [64*24-1:0] chain = 0;
    always @(posedge clk)
        if (chain_load) chain <= accs;
        else if (busy)  chain <= {24'd0, chain[64*24-1:24]};    // shift towards lane 0

    // the chain carries layer (layer-1)'s sums while layer `layer` runs; in the
    // output phase it carries layer 7's sums (no ReLU, signed clamp)
    wire [2:0] src  = outph ? 3'd6 : layer - 3'd1;
    wire [4:0] s_rq = shifts[src*5 +: 5];
    ns64_requant u_rq (.clk(clk), .acc_in(chain[23:0]), .s(s_rq), .relu(!outph), .y(xq));

    // output capture: chain loaded at oc=0, head = sum k at oc=k+1, y valid at oc=k+3
    always @(posedge clk)
        if (outph && oc >= 5'd3 && oc <= 5'd18) y_out[(oc - 5'd3)*8 +: 8] <= xq;

    // ------------------------------------------------------------ 64 MAC lanes
    // Written as ONE process over flat vectors (not 64 instances): same hardware,
    // but Icarus simulates it about 100x faster.
    //   p   <= x * w            (weight word)   / bias_hi * 256 / bias_lo
    //   acc <= p (bias_lo) or acc + p (bias_hi, weights)
    reg [64*16-1:0] p_v   = 0;
    reg [64*24-1:0] acc_v = 0;
    assign accs = acc_v;
    integer j;
    always @(posedge clk)
        if (k1 != K_NONE || k2 != K_NONE)       // idle: hold (also keeps Icarus fast)
        for (j = 0; j < 64; j = j + 1) begin
            case (k1)
                K_W:     p_v[j*16 +: 16] <= x_bus * $signed(rdata[j*8 +: 8]);
                K_HI:    p_v[j*16 +: 16] <= {rdata[j*8 +: 8], 8'h00};   // signed high byte * 256
                default: p_v[j*16 +: 16] <= {8'h00, rdata[j*8 +: 8]};   // unsigned low byte
            endcase
            case (k2)
                K_LO:      acc_v[j*24 +: 24] <= {{8{p_v[j*16+15]}}, p_v[j*16 +: 16]};
                K_HI, K_W: acc_v[j*24 +: 24] <= acc_v[j*24 +: 24] + {{8{p_v[j*16+15]}}, p_v[j*16 +: 16]};
                default:   ;
            endcase
        end
endmodule
