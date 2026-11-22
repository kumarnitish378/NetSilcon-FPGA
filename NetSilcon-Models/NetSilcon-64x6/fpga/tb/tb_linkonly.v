// tb_linkonly : the link-diagnosis top (no engine, no RAM) over its UART pins.
`timescale 1ns/1ps
module tb_linkonly;
    `include "ns64_builtin.vh"
    localparam BIT = 234;
    reg clk = 0;  always #18.5185 clk = ~clk;
    reg rx = 1;  wire tx;  wire [5:0] leds;
    tangnano20k_ns64_linkonly dut (.clk(clk), .uart_rx(rx), .uart_tx(tx), .leds(leds));
    reg [7:0] r [0:63];
    integer errors = 0, i, n, m;
    task send_byte(input [7:0] b); begin
        rx = 0; repeat (BIT) @(posedge clk);
        for (n = 0; n < 8; n = n + 1) begin rx = b[n]; repeat (BIT) @(posedge clk); end
        rx = 1; repeat (BIT) @(posedge clk); end endtask
    task recv_byte(output [7:0] b); integer q; begin
        @(negedge tx); repeat (BIT/2) @(posedge clk);
        for (q = 0; q < 8; q = q + 1) begin repeat (BIT) @(posedge clk); b[q] = tx; end
        repeat (BIT) @(posedge clk); end endtask
    task recv_n(input integer k); begin for (m = 0; m < k; m = m + 1) recv_byte(r[m]); end endtask
    initial begin
        repeat (20) @(posedge clk);
        fork begin send_byte(8'hA5); for (i = 0; i < 16; i = i + 1) send_byte(i * 7); end recv_n(20); join
        if (r[0] !== 8'h5A) errors = errors + 1;
        for (i = 0; i < 16; i = i + 1) if (r[1 + i] !== i * 7) errors = errors + 1;
        $display("echo inference: hdr %h y0 %0d y15 %0d latency %0d", r[0], r[1], r[16], {r[19], r[18]});
        if ({r[19], r[18]} !== 16'd448) errors = errors + 1;
        fork send_byte(8'hC5); recv_n(7); join
        $display("info: %h %h %h %h %h %h %h", r[0], r[1], r[2], r[3], r[4], r[5], r[6]);
        if (r[0] !== 8'h5C || {r[4], r[3], r[2], r[1]} !== BUILTIN_CRC32) errors = errors + 1;
        fork begin send_byte(8'hD2); send_byte(8'd8); send_byte(8'd2); end recv_n(9); join
        for (i = 0; i < 8; i = i + 1) if (r[1 + i] !== i) errors = errors + 1;
        $display("pattern: %h %h %h ... %h", r[0], r[1], r[2], r[8]);
        $display("errors %0d", errors);
        if (errors == 0) $display("RESULT: PASS"); else $display("RESULT: FAIL");
        $finish;
    end
endmodule
