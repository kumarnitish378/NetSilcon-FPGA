// Simulates the Tang Nano 20K self-test top and decodes its UART message.
`timescale 1ns/1ps
module tb_board;
    reg clk = 0;
    always #18.5 clk = ~clk;                 // 27 MHz
    reg btn = 0;
    wire [5:0] leds;
    wire tx;
    tangnano20k_selftest dut (.clk(clk), .btn_s1(btn), .leds(leds), .uart_tx(tx));

    localparam BIT = 234;                    // clocks per UART bit
    reg [7:0] c; integer i, nchar = 0;
    initial begin
        forever begin
            @(negedge tx);                   // start bit
            repeat (BIT/2) @(posedge clk);
            for (i = 0; i < 8; i = i + 1) begin repeat (BIT) @(posedge clk); c[i] = tx; end
            repeat (BIT) @(posedge clk);
            if (c != 8'h0D && c != 8'h0A) $write("%c", c);
            if (c == 8'h0A) begin
                $display("");
                $display("LEDs (1 = on): done=%b fault=%b FAIL=%b PASS=%b running=%b",
                         ~leds[5], ~leds[4], ~leds[3], ~leds[2], ~leds[1]);
                $finish;
            end
        end
    end
    initial begin #50_000_000; $display("TIMEOUT"); $finish; end
endmodule
