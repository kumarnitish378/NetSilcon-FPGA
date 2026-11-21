// =============================================================================
// NetSilcon-6x4 top : 4 -> 6 -> 6 -> 6 -> 6 -> 2, five pipelined layers
//
//   * PHASES=1 : one inference per clock,     result after 10 clocks (144 multipliers)
//   * PHASES=2 : one inference per 2 clocks,  result after 15 clocks (72 multipliers,
//                fits the 96 DSP 9x9 multipliers of the Tang Nano 20K)
//     With PHASES=2, assert in_valid at most every second clock.
//   * 144 int8 weights + 26 int16 biases live in registers.
//     - At power-up they are initialised from gen/weights.mem and gen/biases.mem
//     - They can be rewritten at any time through the param_* port
//       (address 0..143 = weights, 144..169 = biases, 170..174 = layer shifts)
//       -> model update path. Shifts start from gen/netsilcon_params.vh.
//   * Only the network SHAPE is fixed in hardware; every number is loadable.
//
//   x_in  : x0 = [7:0] current, x1 = [15:8] voltage, x2 = [23:16] speed, x3 = [31:24] temp
//   y_out : y0 = [7:0] healthy score, y1 = [15:8] fault score (signed int8)
// =============================================================================
module netsilcon_top #(
    parameter PHASES      = 2,             // 1 = fully parallel (144 mults), 2 = time-shared (72 mults)
    parameter WEIGHT_FILE = "weights.mem",
    parameter BIAS_FILE   = "biases.mem"
)(
    input  wire        clk,
    input  wire        in_valid,
    input  wire [31:0] x_in,
    output wire        out_valid,
    output wire [15:0] y_out,
    output wire        fault,          // 1 when fault score > healthy score
    // parameter write port (model update)
    input  wire        param_we,
    input  wire [7:0]  param_addr,
    input  wire [15:0] param_data
);
    `include "netsilcon_params.vh"

    // ------------------------------------------------------------ parameter registers
    reg [7:0]  w_mem [0:143];
    reg [15:0] b_mem [0:25];
    reg [3:0]  sh1 = SHIFT1, sh2 = SHIFT2, sh3 = SHIFT3, sh4 = SHIFT4, sh5 = SHIFT5;
    initial begin
        $readmemh(WEIGHT_FILE, w_mem);
        $readmemh(BIAS_FILE,   b_mem);
    end
    always @(posedge clk)
        if (param_we) begin
            if (param_addr < 8'd144)      w_mem[param_addr]           <= param_data[7:0];
            else if (param_addr < 8'd170) b_mem[param_addr - 8'd144]  <= param_data;
            else case (param_addr)
                8'd170: sh1 <= param_data[3:0];
                8'd171: sh2 <= param_data[3:0];
                8'd172: sh3 <= param_data[3:0];
                8'd173: sh4 <= param_data[3:0];
                8'd174: sh5 <= param_data[3:0];
                default: ;
            endcase
        end

    // flatten into buses: layer L uses a contiguous slice
    wire [144*8-1:0] W;
    wire [26*16-1:0] B;
    genvar k;
    generate
        for (k = 0; k < 144; k = k + 1) begin : wflat assign W[k*8  +: 8]  = w_mem[k]; end
        for (k = 0; k < 26;  k = k + 1) begin : bflat assign B[k*16 +: 16] = b_mem[k]; end
    endgenerate

    // ------------------------------------------------------------ 5-stage pipeline
    wire [6*8-1:0] a1, a2, a3, a4;
    wire           v1, v2, v3, v4;

    nn_layer #(.N_IN(4), .N_OUT(6), .RELU(1), .PHASES(PHASES)) L1 (
        .clk(clk), .shift(sh1), .in_valid(in_valid), .x(x_in),
        .w(W[0*8  +: 24*8]), .b(B[0*16  +: 6*16]), .out_valid(v1), .y(a1));

    nn_layer #(.N_IN(6), .N_OUT(6), .RELU(1), .PHASES(PHASES)) L2 (
        .clk(clk), .shift(sh2), .in_valid(v1), .x(a1),
        .w(W[24*8 +: 36*8]), .b(B[6*16  +: 6*16]), .out_valid(v2), .y(a2));

    nn_layer #(.N_IN(6), .N_OUT(6), .RELU(1), .PHASES(PHASES)) L3 (
        .clk(clk), .shift(sh3), .in_valid(v2), .x(a2),
        .w(W[60*8 +: 36*8]), .b(B[12*16 +: 6*16]), .out_valid(v3), .y(a3));

    nn_layer #(.N_IN(6), .N_OUT(6), .RELU(1), .PHASES(PHASES)) L4 (
        .clk(clk), .shift(sh4), .in_valid(v3), .x(a3),
        .w(W[96*8 +: 36*8]), .b(B[18*16 +: 6*16]), .out_valid(v4), .y(a4));

    nn_layer #(.N_IN(6), .N_OUT(2), .RELU(0), .PHASES(PHASES)) L5 (
        .clk(clk), .shift(sh5), .in_valid(v4), .x(a4),
        .w(W[132*8 +: 12*8]), .b(B[24*16 +: 2*16]), .out_valid(out_valid), .y(y_out));

    assign fault = $signed(y_out[15:8]) > $signed(y_out[7:0]);
endmodule
