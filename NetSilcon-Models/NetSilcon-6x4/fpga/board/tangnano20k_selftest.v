// =============================================================================
// NetSilcon-6x4 on Sipeed Tang Nano 20K : on-board self-test
//
// At power-up (and every time button S1 is pressed) the FPGA streams all
// golden test vectors through the network, compares every output with the
// Python int8 model and reports the result:
//
//   LED0  blinking  : design is alive (heartbeat)
//   LED1  on        : test running
//   LED2  on        : PASS  (every output matched bit for bit)
//   LED3  on        : FAIL
//   LED4  on        : last vector was classified as FAULT
//   LED5  on        : test finished
//   UART  115200 8N1 (BL616 USB serial):
//         "NetSilcon-6x4: PASS err=0x0000 n=0x240"  (n = vectors checked, hex)
//
// No PC software needed: plug in USB-C, load the bitstream, watch the LEDs.
// =============================================================================
module tangnano20k_selftest (
    input  wire       clk,        // 27 MHz, pin 4
    input  wire       btn_s1,     // S1, pin 88, high when pressed
    output wire [5:0] leds,       // pins 15..20, active low
    output wire       uart_tx     // pin 69 -> BL616 USB-UART
);
    `include "num_vectors.vh"
    localparam PHASES = 2;

    // ---------------------------------------------------------------- golden vector ROMs
    reg [31:0] rom_in  [0:NUM_VECTORS-1];
    reg [15:0] rom_out [0:NUM_VECTORS-1];
    initial begin
        $readmemh("test_in.mem",  rom_in);
        $readmemh("test_out.mem", rom_out);
    end

    // ---------------------------------------------------------------- start: power-up or S1
    reg [2:0]  btn_sync = 0;
    reg [19:0] por = 0;                               // ~39 ms power-on delay
    reg        start = 0;
    always @(posedge clk) begin
        btn_sync <= {btn_sync[1:0], btn_s1};
        start    <= 1'b0;
        if (!por[19]) begin
            por <= por + 1'b1;
            if (por == 20'h7FFFF) start <= 1'b1;
        end else if (btn_sync[2:1] == 2'b01)
            start <= 1'b1;
    end

    // ---------------------------------------------------------------- feeder
    reg        running = 0, done = 0, phase = 0;
    reg [9:0]  idx = 0, got = 0;
    reg [31:0] vin_q = 0;
    reg        in_valid = 0;
    reg [15:0] errors = 0;
    reg        last_fault = 0;

    wire        out_valid, fault;
    wire [15:0] y_out;

    always @(posedge clk) begin
        vin_q    <= rom_in[idx];                      // block-RAM read, 1 clock latency
        in_valid <= 1'b0;
        if (start) begin
            running <= 1'b1; done <= 1'b0; phase <= 1'b0; idx <= 0;
        end else if (running && idx < NUM_VECTORS) begin
            phase <= ~phase;
            if (phase) begin                          // one vector every 2 clocks
                in_valid <= 1'b1;
                idx      <= idx + 1'b1;
            end
        end
        if (running && got == NUM_VECTORS) begin
            running <= 1'b0; done <= 1'b1;
        end
    end

    netsilcon_top #(.PHASES(PHASES)) nn (
        .clk(clk), .in_valid(in_valid), .x_in(vin_q),
        .out_valid(out_valid), .y_out(y_out), .fault(fault),
        .param_we(1'b0), .param_addr(8'd0), .param_data(16'd0));

    // ---------------------------------------------------------------- checker
    reg [15:0] exp_q = 0;
    always @(posedge clk) begin
        exp_q <= rom_out[got];
        if (start) begin
            got <= 0; errors <= 0;
        end else if (out_valid && got < NUM_VECTORS) begin
            if (y_out !== exp_q) errors <= errors + 1'b1;
            last_fault <= fault;
            got <= got + 1'b1;
        end
    end

    // ---------------------------------------------------------------- report over UART
    reg  done_d = 0;
    reg  msg_go = 0;
    always @(posedge clk) begin done_d <= done; msg_go <= done & ~done_d; end

    function [7:0] hexc(input [3:0] n);
        hexc = (n < 10) ? 8'h30 + n : 8'h41 + n - 10;
    endfunction

    wire pass = (errors == 0) && (got == NUM_VECTORS);
    reg [5:0] ci = 0;
    reg [7:0] ch;
    always @* begin
        case (ci)
             0: ch="N";  1: ch="e";  2: ch="t";  3: ch="S";  4: ch="i";  5: ch="l";  6: ch="c";
             7: ch="o";  8: ch="n";  9: ch="-"; 10: ch="6"; 11: ch="x"; 12: ch="4"; 13: ch=":";
            14: ch=" "; 15: ch= pass ? "P" : "F"; 16: ch= pass ? "A" : "A";
            17: ch= pass ? "S" : "I"; 18: ch= pass ? "S" : "L"; 19: ch=" ";
            20: ch="e"; 21: ch="r"; 22: ch="r"; 23: ch="="; 24: ch="0"; 25: ch="x";
            26: ch=hexc(errors[15:12]); 27: ch=hexc(errors[11:8]); 28: ch=hexc(errors[7:4]); 29: ch=hexc(errors[3:0]);
            30: ch=" "; 31: ch="n"; 32: ch="=";  33: ch="0"; 34: ch="x";
            35: ch=hexc({2'b00, got[9:8]}); 36: ch=hexc(got[7:4]); 37: ch=hexc(got[3:0]);
            38: ch=8'h0D; 39: ch=8'h0A;
            default: ch=8'h00;
        endcase
    end

    reg  sending = 0, tx_start = 0;
    wire tx_busy;
    always @(posedge clk) begin
        tx_start <= 1'b0;
        if (msg_go) begin sending <= 1'b1; ci <= 0; end
        else if (sending && !tx_busy && !tx_start) begin
            if (ci == 40) sending <= 1'b0;
            else begin tx_start <= 1'b1; ci <= ci + 1'b1; end
        end
    end
    reg [7:0] tx_byte = 0;
    always @(posedge clk) if (sending && !tx_busy && !tx_start && ci < 40) tx_byte <= ch;

    uart_tx #(.CLKS_PER_BIT(234)) u_tx (    // 27 MHz / 115200
        .clk(clk), .start(tx_start), .data(tx_byte), .tx(uart_tx), .busy(tx_busy));

    // ---------------------------------------------------------------- LEDs (active low)
    reg [24:0] hb = 0;
    always @(posedge clk) hb <= hb + 1'b1;
    assign leds = ~{done, last_fault, done & ~pass, done & pass, running, hb[24]};
endmodule

// -----------------------------------------------------------------------------
// Minimal UART transmitter, 8N1
// -----------------------------------------------------------------------------
module uart_tx #(parameter CLKS_PER_BIT = 234) (
    input  wire       clk,
    input  wire       start,
    input  wire [7:0] data,
    output reg        tx = 1'b1,
    output wire       busy
);
    reg [9:0]  sh  = 10'h3FF;
    reg [3:0]  bit_n = 0;
    reg [15:0] cnt = 0;
    reg        act = 0;
    assign busy = act | start;
    always @(posedge clk) begin
        if (!act) begin
            tx <= 1'b1;
            if (start) begin sh <= {1'b1, data, 1'b0}; act <= 1'b1; bit_n <= 0; cnt <= 0; end
        end else begin
            tx <= sh[0];
            if (cnt == CLKS_PER_BIT - 1) begin
                cnt <= 0; sh <= {1'b1, sh[9:1]}; bit_n <= bit_n + 1'b1;
                if (bit_n == 9) act <= 1'b0;
            end else cnt <= cnt + 1'b1;
        end
    end
endmodule
