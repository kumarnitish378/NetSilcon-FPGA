// =============================================================================
// NetSilcon-LM-0 : character language model engine
//   context 32 symbols -> embedding (8 each) -> 256 -> 64 -> 64 -> 64 -> 42 logits
//
// Same datapath as the verified NetSilcon-64x6 engine (ns64_engine.v): 64 MAC lanes,
// lane j = neuron j of every layer; each clock ONE input value is broadcast to all
// lanes and each lane adds x * w from its own byte column of the weight RAM.
// Per layer with N_in inputs: t=0 bias lo, t=1 bias hi, t=2..N_in+1 weights,
// two drain clocks -> N_in + 4 clocks.
//
// Differences to ns64_engine:
//   * layer 1 has 256 inputs, streamed from the embedding ROM:
//       x_i = EMB[ctx[i/8]][i%8], ctx[0] = oldest symbol (ctx_in bits 191:186)
//   * 4 layers, word bases [0, 258, 324, 390]
//   * output phase streams 42 logits through the shared requantizer (signed clamp)
//     into y_out and a running argmax (strict '>', so ties keep the lowest index)
//
// Total: 510 clocks per character from start to done (measured in tb_engine).
// Math is identical to python/model/nslm.py (bit-exact).
// =============================================================================
module nslm_engine (
    input  wire          clk,
    input  wire          start,          // 1-clock pulse, ctx_in must stay stable while busy
    input  wire [191:0]  ctx_in,         // 32 x 6-bit symbols, newest in bits 5:0
    input  wire [19:0]   shifts,         // 4 x 5 bits, layer 0 in bits 4:0
    output reg           busy = 1'b0,
    output reg           done = 1'b0,    // 1-clock pulse: y_out / next_sym valid
    output reg  [335:0]  y_out = 336'd0, // 42 signed logits, logit 0 in bits 7:0
    output reg  [5:0]    next_sym = 6'd0,// argmax
    // weight RAM read port
    output wire [8:0]    raddr,
    output wire          ram_re,
    input  wire [511:0]  rdata,
    // embedding ROM read port (registered read, 1 clock)
    output wire [8:0]    eaddr,
    input  wire [7:0]    edata
);
    localparam K_NONE = 2'd0, K_LO = 2'd1, K_HI = 2'd2, K_W = 2'd3;
    localparam NV = 42;

    // ------------------------------------------------------------ sequencer
    reg        run   = 1'b0;
    reg        outph = 1'b0;
    reg [1:0]  layer = 2'd0;              // 0..3
    reg [8:0]  t     = 9'd0;
    reg [5:0]  oc    = 6'd0;

    wire [8:0] n_in = (layer == 2'd0) ? 9'd256 : 9'd64;
    wire [8:0] base = (layer == 2'd0) ? 9'd0   : (layer == 2'd1) ? 9'd258 :
                      (layer == 2'd2) ? 9'd324 : 9'd390;
    assign raddr  = base + t;
    assign ram_re = run;

    wire [1:0] k0 = !run             ? K_NONE :
                    (t == 9'd0)      ? K_LO   :
                    (t == 9'd1)      ? K_HI   :
                    (t < n_in + 9'd2) ? K_W   : K_NONE;

    wire layer_end  = run && (t == n_in + 9'd3);
    wire chain_load = (run && t == 9'd0 && layer != 2'd0) || (outph && oc == 6'd0);

    always @(posedge clk) begin
        done <= 1'b0;
        if (start && !busy) begin
            busy <= 1'b1; run <= 1'b1; layer <= 2'd0; t <= 9'd0;
        end else if (run) begin
            if (layer_end) begin
                t <= 9'd0;
                if (layer == 2'd3) begin run <= 1'b0; outph <= 1'b1; oc <= 6'd0; end
                else layer <= layer + 2'd1;
            end else t <= t + 9'd1;
        end else if (outph) begin
            oc <= oc + 6'd1;
            if (oc == NV + 2) begin outph <= 1'b0; busy <= 1'b0; done <= 1'b1; end
        end
    end

    // ------------------------------------------------------------ layer-1 input stream
    // weight i = t-2 is read at clock t; x_i must be valid one clock later.
    // i = 8*p + d  ->  ROM address = symbol(ctx[p]) * 8 + d   (ROM output is registered)
    wire [8:0] wi  = t - 9'd2;
    wire [4:0] p   = wi[7:3];
    wire [5:0] sym = ctx_in[(5'd31 - p) * 6 +: 6];
    assign eaddr = {sym, wi[2:0]};
    wire signed [7:0] x_l1 = $signed(edata);      // EMB values are 0..127

    // ------------------------------------------------------------ word-kind pipeline
    reg [1:0] k1 = K_NONE, k2 = K_NONE;
    always @(posedge clk) begin k1 <= k0; k2 <= k1; end

    // ------------------------------------------------------------ requantizer + chain
    wire [7:0] xq;
    wire signed [7:0] x_bus = (layer == 2'd0 && run) ? x_l1 : $signed(xq);

    wire [64*24-1:0] accs;
    reg  [64*24-1:0] chain = 0;
    always @(posedge clk)
        if (chain_load) chain <= accs;
        else if (busy)  chain <= {24'd0, chain[64*24-1:24]};

    wire [1:0] src  = outph ? 2'd3 : (layer == 2'd0) ? 2'd0 : layer - 2'd1;
    wire [4:0] s_rq = shifts[src*5 +: 5];
    nslm_requant u_rq (.clk(clk), .acc_in(chain[23:0]), .s(s_rq), .relu(!outph), .y(xq));

    // output capture + argmax: chain loaded at oc=0, logit k valid at oc = k+3
    reg signed [7:0] best = 8'sd0;
    wire [5:0] k_out = oc - 6'd3;
    always @(posedge clk)
        if (outph && oc >= 6'd3 && oc <= NV + 2) begin
            y_out[k_out*8 +: 8] <= xq;
            if (k_out == 6'd0 || $signed(xq) > best) begin best <= $signed(xq); next_sym <= k_out; end
        end

    // ------------------------------------------------------------ 64 MAC lanes (as ns64_engine)
    reg [64*16-1:0] p_v   = 0;
    reg [64*24-1:0] acc_v = 0;
    assign accs = acc_v;
    integer j;
    always @(posedge clk)
        if (k1 != K_NONE || k2 != K_NONE)
        for (j = 0; j < 64; j = j + 1) begin
            case (k1)
                K_W:     p_v[j*16 +: 16] <= x_bus * $signed(rdata[j*8 +: 8]);
                K_HI:    p_v[j*16 +: 16] <= {rdata[j*8 +: 8], 8'h00};
                default: p_v[j*16 +: 16] <= {8'h00, rdata[j*8 +: 8]};
            endcase
            case (k2)
                K_LO:      acc_v[j*24 +: 24] <= {{8{p_v[j*16+15]}}, p_v[j*16 +: 16]};
                K_HI, K_W: acc_v[j*24 +: 24] <= acc_v[j*24 +: 24] + {{8{p_v[j*16+15]}}, p_v[j*16 +: 16]};
                default:   ;
            endcase
        end
endmodule
