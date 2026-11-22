// =============================================================================
// Testbench for the live-UART top: acts like the PC.
//  1. Sends golden test vectors as UART frames, decodes the 5-byte replies,
//     checks y0/y1 bit-exact against the Python model, flags and latency.
//  2. Sends a stray byte + a half frame, waits for the timeout, then checks
//     the next frame still works (receiver resynchronises).
// =============================================================================
`timescale 1ns/1ps
module tb_uart;
    `include "num_vectors.vh"
    localparam BIT  = 234;                 // clocks per UART bit
    localparam NTEST = 40;

    reg clk = 0;  always #18.5185 clk = ~clk;   // 27 MHz
    reg rx = 1;
    wire tx;
    wire [5:0] leds;
    tangnano20k_uart #(.CLKS_PER_BIT(BIT), .TIMEOUT(20000)) dut (
        .clk(clk), .btn_s1(1'b0), .uart_rx(rx), .uart_tx(tx), .leds(leds));

    reg [31:0] vin  [0:NUM_VECTORS-1];
    reg [15:0] vout [0:NUM_VECTORS-1];

    task send_byte(input [7:0] b);
        integer i;
        begin
            rx = 0; repeat (BIT) @(posedge clk);                 // start bit
            for (i = 0; i < 8; i = i + 1) begin rx = b[i]; repeat (BIT) @(posedge clk); end
            rx = 1; repeat (BIT) @(posedge clk);                 // stop bit
        end
    endtask

    task recv_byte(output [7:0] b);
        integer i;
        begin
            @(negedge tx);                                       // start bit edge
            repeat (BIT/2) @(posedge clk);
            for (i = 0; i < 8; i = i + 1) begin repeat (BIT) @(posedge clk); b[i] = tx; end
            repeat (BIT) @(posedge clk);                         // stop bit
        end
    endtask

    reg [7:0] r0, r1, r2, r3, r4;
    integer n, errors = 0, lat_bad = 0, flag_bad = 0;
    reg exp_fault;

    task frame_and_check(input integer k);
        begin
            fork
                begin
                    send_byte(8'hA5);
                    send_byte(vin[k][7:0]);   send_byte(vin[k][15:8]);
                    send_byte(vin[k][23:16]); send_byte(vin[k][31:24]);
                end
                begin
                    recv_byte(r0); recv_byte(r1); recv_byte(r2); recv_byte(r3); recv_byte(r4);
                end
            join
            exp_fault = $signed(vout[k][15:8]) > $signed(vout[k][7:0]);
            if (r0 !== 8'h5A || {r2, r1} !== vout[k]) begin
                errors = errors + 1;
                $display("MISMATCH vector %0d: got %h %h %h %h %h, expected y=%h", k, r0, r1, r2, r3, r4, vout[k]);
            end
            if (r3[0] !== exp_fault) flag_bad = flag_bad + 1;
            if (r4 != 8'd15) lat_bad = lat_bad + 1;
        end
    endtask

    initial begin
        $readmemh("test_in.mem",  vin);
        $readmemh("test_out.mem", vout);
        repeat (50) @(posedge clk);

        for (n = 0; n < NTEST; n = n + 1) frame_and_check(n);
        $display("Frames checked      : %0d", NTEST);
        $display("Output mismatches   : %0d", errors);
        $display("Fault-flag errors   : %0d", flag_bad);
        $display("Latency reported    : %0d clocks (wrong on %0d frames)", r4, lat_bad);

        // ---- robustness: stray byte, then a half frame, then wait for timeout
        send_byte(8'h33);
        send_byte(8'hA5); send_byte(8'h10); send_byte(8'h20);
        repeat (25000) @(posedge clk);
        frame_and_check(NTEST);
        $display("Resync after junk   : %s", (errors == 0) ? "OK" : "FAILED");
        $display("LED5 (frame error)  : %s", leds[5] ? "off" : "on (expected)");

        if (errors == 0 && flag_bad == 0 && lat_bad == 0 && !leds[5])
            $display("RESULT: PASS - live UART inference matches the Python int8 model");
        else
            $display("RESULT: FAIL");
        $finish;
    end
    initial begin #400_000_000; $display("TIMEOUT"); $finish; end
endmodule
