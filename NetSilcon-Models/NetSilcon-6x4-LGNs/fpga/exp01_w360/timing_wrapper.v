// timing_wrapper.v -- FOR MEASUREMENT ONLY.
// Shift 32 input bits in serially, run the combinational core, capture outputs.
// The registers here exist only so nextpnr can time reg -> core -> reg.
// The core itself (netsilcon_6x4_lgn_exp01_w360) has zero registers.
module timing_wrapper (input wire clk, input wire din, output wire dout);
    reg [31:0] sh = 32'd0;
    reg [4:0]  q  = 5'd0;
    wire [1:0] speed; wire [2:0] steer;
    always @(posedge clk) sh <= {sh[30:0], din};
    netsilcon_6x4_lgn_exp01_w360 core(.fl(sh[31:24]), .fr(sh[23:16]), .rl(sh[15:8]), .rr(sh[7:0]),
               .speed(speed), .steer(steer));
    always @(posedge clk) q <= {speed, steer};
    assign dout = ^q;
endmodule
