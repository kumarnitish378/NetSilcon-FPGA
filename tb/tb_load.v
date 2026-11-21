// =============================================================================
// Model-update testbench: plays the PC, talks UART to the real board top.
//   1. Info -> built-in model.  Motor vectors bit-exact.
//   2. Upload irrigation with a WRONG CRC -> rejected, motor model still runs.
//   3. Upload irrigation correctly -> accepted, CRC reported, irrigation vectors
//      bit-exact (new weights, biases AND new shifts are in use).
//   4. Interrupted upload (half the bytes, then silence) -> timeout, irrigation kept.
//   5. Upload the motor model again -> motor vectors bit-exact again.
// =============================================================================
`timescale 1ns/1ps
module tb_load;
    localparam BIT = 234, NV = 20, IMGN = 203;

    reg clk = 0;  always #18.5185 clk = ~clk;   // 27 MHz
    reg rx = 1;
    wire tx;
    wire [5:0] leds;
    tangnano20k_uart #(.CLKS_PER_BIT(BIT), .TIMEOUT(20000)) dut (
        .clk(clk), .btn_s1(1'b0), .uart_rx(rx), .uart_tx(tx), .leds(leds));

    reg [7:0]  img_m [0:IMGN-1], img_i [0:IMGN-1];
    reg [31:0] tin_m [0:575], tin_i [0:575];
    reg [15:0] tout_m[0:575], tout_i[0:575];

    task send_byte(input [7:0] b);
        integer i;
        begin
            rx = 0; repeat (BIT) @(posedge clk);
            for (i = 0; i < 8; i = i + 1) begin rx = b[i]; repeat (BIT) @(posedge clk); end
            rx = 1; repeat (BIT) @(posedge clk);
        end
    endtask
    task recv_byte(output [7:0] b);
        integer i;
        begin
            @(negedge tx); repeat (BIT/2) @(posedge clk);
            for (i = 0; i < 8; i = i + 1) begin repeat (BIT) @(posedge clk); b[i] = tx; end
            repeat (BIT) @(posedge clk);
        end
    endtask

    reg [7:0] r0, r1, r2, r3, r4;
    task recv5; begin recv_byte(r0); recv_byte(r1); recv_byte(r2); recv_byte(r3); recv_byte(r4); end endtask

    integer fails = 0, n, k, bad;

    task info(input [7:0] exp_src, input [15:0] exp_crc, input [255:0] what);
        begin
            fork send_byte(8'hC5); recv5; join
            $display("  info: header %h  crc %h%h  source %0d  loads %0d   (%0s)", r0, r2, r1, r3, r4, what);
            if (r0 !== 8'h5C || r3 !== exp_src || {r2, r1} !== exp_crc) begin fails = fails + 1; $display("  ^^ FAIL"); end
        end
    endtask

    // which: 0 = motor, 1 = irrigation, 2 = irrigation with corrupted CRC, 3 = irrigation cut in half
    task upload(input integer which, input [7:0] exp_status);
        integer i, last;
        begin
            last = (which == 3) ? 100 : IMGN;
            fork
                begin
                    send_byte(8'hC3);
                    for (i = 0; i < last; i = i + 1)
                        if (which == 0) send_byte(img_m[i]);
                        else if (which == 2 && i == IMGN-1) send_byte(img_i[i] ^ 8'h01);  // flip 1 CRC bit
                        else send_byte(img_i[i]);
                end
                recv5;
            join
            $display("  load reply: header %h  status %0d  crc %h%h  loads %0d", r0, r1, r3, r2, r4);
            if (r0 !== 8'h3C || r1 !== exp_status) begin fails = fails + 1; $display("  ^^ FAIL"); end
        end
    endtask

    task run_vectors(input integer which, input [255:0] what);
        begin
            bad = 0;
            for (k = 0; k < NV; k = k + 1) begin
                fork
                    begin
                        send_byte(8'hA5);
                        if (which == 0) begin
                            send_byte(tin_m[k][7:0]); send_byte(tin_m[k][15:8]); send_byte(tin_m[k][23:16]); send_byte(tin_m[k][31:24]);
                        end else begin
                            send_byte(tin_i[k][7:0]); send_byte(tin_i[k][15:8]); send_byte(tin_i[k][23:16]); send_byte(tin_i[k][31:24]);
                        end
                    end
                    recv5;
                join
                if ({r2, r1} !== ((which == 0) ? tout_m[k] : tout_i[k]) || r4 !== 8'd15) bad = bad + 1;
            end
            $display("  %0d %0s vectors: %0d mismatches", NV, what, bad);
            if (bad) fails = fails + 1;
        end
    endtask

    initial begin
        $readmemh("motor_fault_image.mem", img_m); $readmemh("irrigation_image.mem", img_i);
        $readmemh("motor_fault_tin.mem", tin_m);   $readmemh("motor_fault_tout.mem", tout_m);
        $readmemh("irrigation_tin.mem", tin_i);    $readmemh("irrigation_tout.mem", tout_i);
        repeat (50) @(posedge clk);

        $display("1. Power-up");
        info(0, 16'h0000, "built-in");
        run_vectors(0, "motor");

        $display("2. Upload irrigation with a corrupted CRC");
        upload(2, 1);
        info(0, 16'h0000, "must still be built-in");
        run_vectors(0, "motor");

        $display("3. Upload irrigation");
        upload(1, 0);
        info(1, {img_i[IMGN-2], img_i[IMGN-1]}, "irrigation");
        $display("  LED4 (uploaded model) : %s", leds[4] ? "off" : "on");
        if (leds[4]) fails = fails + 1;
        run_vectors(1, "irrigation");

        $display("4. Interrupted upload (100 of 203 bytes, then silence)");
        upload(3, 2);
        run_vectors(1, "irrigation (kept)");

        $display("5. Upload the motor model again");
        upload(0, 0);
        info(1, {img_m[IMGN-2], img_m[IMGN-1]}, "motor, uploaded");
        run_vectors(0, "motor");

        if (fails == 0) $display("RESULT: PASS - model update over UART works, bad uploads never touch the running model");
        else            $display("RESULT: FAIL (%0d checks failed)", fails);
        $finish;
    end
endmodule
