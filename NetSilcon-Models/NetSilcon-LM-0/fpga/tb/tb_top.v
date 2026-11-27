// =============================================================================
// tb_top : the Tang Nano 20K top over the real UART path (115200 8N1, 27 MHz)
//   Types gen/uart_in.mem into uart_rx like a PC terminal would (upper case, CR,
//   CR LF), captures every byte on uart_tx and compares it with gen/uart_out.mem
//   (echo in lower case + CR LF + the answer the Python model gives).
// =============================================================================
`timescale 1ns/1ps
module tb_top;
    `include "num_vectors.vh"
    reg clk = 0;
    always #18.518 clk = ~clk;
    localparam BIT = 234;                                 // clocks per bit

    reg rx = 1'b1; wire tx; wire [5:0] leds;
    tangnano20k_lm dut (.clk(clk), .uart_rx(rx), .uart_tx(tx), .leds(leds));

    reg [7:0] uin [0:N_UIN-1];
    reg [7:0] uout [0:N_UOUT-1];
    reg [7:0] got [0:N_UOUT+63];
    integer i, b, nrx = 0, errors = 0;

    task send(input [7:0] v);
        begin
            rx = 0; repeat (BIT) @(posedge clk);
            for (b = 0; b < 8; b = b + 1) begin rx = v[b]; repeat (BIT) @(posedge clk); end
            rx = 1; repeat (BIT * 2) @(posedge clk);
        end
    endtask

    // receiver on uart_tx
    reg [7:0] r;
    initial forever begin
        @(negedge tx);
        repeat (BIT + BIT / 2) @(posedge clk);
        for (i = 0; i < 8; i = i + 1) begin r[i] = tx; repeat (BIT) @(posedge clk); end
        got[nrx] = r; nrx = nrx + 1;
    end

    integer k, wait_clk;
    initial begin
        $readmemh("uart_in.mem", uin);
        $readmemh("uart_out.mem", uout);
        repeat (100) @(posedge clk);
        for (k = 0; k < N_UIN; k = k + 1) begin
            send(uin[k]);
            if (uin[k] == 8'h0D || uin[k] == 8'h0A) begin      // wait for the answer line
                wait_clk = 0;
                while (wait_clk < 400000 && !(nrx > 1 && got[nrx-1] == 8'h0A && leds[0] == 1'b1 && dut.st == 0)) begin
                    @(posedge clk); wait_clk = wait_clk + 1;
                end
            end
        end
        repeat (BIT * 30) @(posedge clk);
        $write(">> ");
        for (k = 0; k < nrx; k = k + 1) begin
            if (got[k] == 8'h0A) $write("\n>> "); else if (got[k] != 8'h0D) $write("%c", got[k]);
            if (k < N_UOUT && got[k] !== uout[k]) errors = errors + 1;
        end
        $display("");
        if (nrx != N_UOUT) errors = errors + 1;
        $display("RESULT top uart bytes_received=%0d expected=%0d mismatches=%0d %s",
                 nrx, N_UOUT, errors, errors == 0 ? "PASS" : "FAIL");
        $finish;
    end
endmodule
