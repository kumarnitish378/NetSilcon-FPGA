// =============================================================================
// NetSilcon-LM-0 : the ONE shared requantizer (copy of ns64_requant.v, renamed) (2-clock pipeline)
//
//   a = relu ? max(acc, 0) : acc
//   v = (a + 2^(s-1)) >>> s            s = 0..23, rounding constant 0 for s = 0
//   y = relu ? clamp(v, 0, 127) : clamp(v, -128, 127)
//
// All neuron sums pass through here one per clock (from the shift chain),
// so the design needs one barrel shifter instead of 64.
// acc_in is valid at clock t -> y is valid at clock t + 2.
// =============================================================================
module nslm_requant (
    input  wire               clk,
    input  wire signed [23:0] acc_in,
    input  wire        [4:0]  s,
    input  wire               relu,
    output reg         [7:0]  y = 8'd0
);
    // stage A: ReLU + rounding constant (25 bits: 24-bit acc + 2^22 can not overflow)
    wire signed [24:0] act  = (relu && acc_in[23]) ? 25'sd0 : {acc_in[23], acc_in};
    wire signed [24:0] half = (s == 5'd0) ? 25'sd0 : (25'sd1 <<< (s - 5'd1));
    reg  signed [24:0] sum  = 25'sd0;
    reg         [4:0]  s_d  = 5'd0;
    reg                r_d  = 1'b0;
    always @(posedge clk) begin
        sum <= act + half;
        s_d <= s;
        r_d <= relu;
    end

    // stage B: arithmetic shift + clamp
    wire signed [24:0] v = sum >>> s_d;
    always @(posedge clk)
        if (r_d) y <= (v > 25'sd127) ? 8'd127 : v[7:0];                 // v >= 0 after ReLU
        else     y <= (v > 25'sd127) ? 8'h7F : (v < -25'sd128) ? 8'h80 : v[7:0];
endmodule
