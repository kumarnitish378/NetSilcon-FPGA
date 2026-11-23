// =============================================================================
// NetSilcon-6x4 : one neural network layer
//
//   For every neuron j (all neurons work at the same time):
//     acc_j = bias_j + sum_i( x_i * w_ji )            20-bit signed
//     hidden layer : acc_j = (acc_j < 0) ? 0 : acc_j  ReLU via the sign bit
//     y_j  = (acc_j + 2^(shift-1)) >>> shift          round + requantize
//     y_j  = clamp to 0..127 (hidden) or -128..127 (output)
//
//   shift is a run-time input (0..15), so a newly loaded model can bring its
//   own scaling. The sum is registered before activation/shift/clamp: that
//   extra pipeline stage keeps the slow multiply-add path short (timing).
//
//   PHASES = 1 : fully parallel. N_IN multipliers per neuron, 1 input / clock,
//                2 clocks latency. (ASIC / large FPGA)
//   PHASES = 2 : time-shared. N_IN/2 multipliers per neuron, used twice.
//                1 input every 2 clocks, 3 clocks latency.
//                Halves the multiplier count so the design fits the 96 DSP
//                9x9 multipliers of the Tang Nano 20K (GW2AR-18).
//   Both modes give bit-identical results.
//
//   Weight layout: w[(j*N_IN + i)*8 +: 8] = weight from input i to neuron j
// =============================================================================
module nn_layer #(
    parameter N_IN   = 4,
    parameter N_OUT  = 6,
    parameter RELU   = 1,        // 1 = hidden layer (ReLU, 0..127), 0 = output layer (signed)
    parameter PHASES = 1         // 1 or 2 (N_IN must be even for 2)
)(
    input  wire                     clk,
    input  wire                     in_valid,
    input  wire [N_IN*8-1:0]        x,        // N_IN signed 8-bit activations
    input  wire [N_IN*N_OUT*8-1:0]  w,        // signed 8-bit weights
    input  wire [N_OUT*16-1:0]      b,        // signed 16-bit biases
    input  wire [3:0]               shift,    // requantization right-shift (0..15)
    output reg                      out_valid,
    output reg  [N_OUT*8-1:0]       y
);
    localparam integer NM   = N_IN / PHASES;          // multipliers per neuron

    // ------------------------------------------------------------ phase control
    reg              ph = 1'b0;                       // 1 = second half in progress (PHASES=2)
    reg [N_IN*8-1:0] xr = 0;                          // latched input for the second half
    reg              sv = 1'b0;                       // full sum registered, ready for activation
    wire [19:0]      halfu = (20'd1 << shift) >> 1;   // rounding constant 2^(shift-1), 0 if shift=0
    initial begin out_valid = 1'b0; y = {N_OUT*8{1'b0}}; end

    generate if (PHASES == 1) begin : ctl1
        always @(posedge clk) begin sv <= in_valid; out_valid <= sv; end
    end else begin : ctl2
        always @(posedge clk) begin
            ph        <= in_valid & ~ph;              // first half this clock -> second half next clock
            sv        <= ph;
            out_valid <= sv;
            if (in_valid & ~ph) xr <= x;
        end
    end endgenerate

    genvar j;
    generate
        for (j = 0; j < N_OUT; j = j + 1) begin : neuron
            // ---- NM shared multipliers + adder tree
            // operand select: first half from x (live input), second half from xr (latched)
            wire [NM*8-1:0] xs = (PHASES == 1 || !ph) ? x[NM*8-1:0]  : xr[N_IN*8-1 -: NM*8];
            wire [NM*8-1:0] ws = (PHASES == 1 || !ph) ? w[j*N_IN*8 +: NM*8]
                                                      : w[(j*N_IN + N_IN - NM)*8 +: NM*8];
            reg signed [19:0] psum;
            integer k;
            always @* begin
                psum = 20'sd0;
                for (k = 0; k < NM; k = k + 1)
                    psum = psum + $signed(xs[k*8 +: 8]) * $signed(ws[k*8 +: 8]);
            end

            wire signed [19:0] bias = {{4{b[j*16+15]}}, b[j*16 +: 16]};
            reg  signed [19:0] acc_r = 20'sd0;        // partial sum after first half
            always @(posedge clk) acc_r <= bias + psum;

            // full sum: one phase -> bias + all products; two phases -> stored half + second half
            wire signed [19:0] acc = (PHASES == 1) ? (bias + psum) : (acc_r + psum);

            reg  signed [19:0] acc_f = 20'sd0;        // pipeline register: complete sum
            always @(posedge clk) if (PHASES == 1 || ph) acc_f <= acc;

            // ---- activation + requantization (next clock)
            wire signed [19:0] act = (RELU && acc_f[19]) ? 20'sd0 : acc_f;   // ReLU: sign bit set -> 0
            wire signed [19:0] v   = (act + $signed(halfu)) >>> shift;
            wire        [7:0]  q   = RELU ? ((v > 127)  ? 8'd127 : v[7:0])
                                          : ((v > 127)  ? 8'h7F   :
                                             (v < -128) ? 8'h80   : v[7:0]);

            always @(posedge clk)
                if (sv) y[j*8 +: 8] <= q;
        end
    endgenerate
endmodule
