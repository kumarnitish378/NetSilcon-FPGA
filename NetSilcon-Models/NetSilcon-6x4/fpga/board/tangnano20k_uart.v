// =============================================================================
// NetSilcon-6x4 on Sipeed Tang Nano 20K : LIVE inference + MODEL UPDATE over USB serial
//
// Protocol (115200 baud, 8N1, through the board's USB-C / BL616 serial port).
// Every reply is 5 bytes.
//
//   1. Inference
//   PC  -> FPGA : 0xA5  x0  x1  x2  x3            (5 bytes)
//                 x0 = current, x1 = voltage, x2 = speed, x3 = temperature,
//                 each already scaled to 0..127  (q = round(value/range*127))
//   FPGA -> PC  : 0x5A  y0  y1  flags  latency
//                 y0 = healthy score, y1 = fault score (signed int8)
//                 flags bit0 = FAULT (y1 > y0)
//                 latency = clocks from input to answer, measured in hardware
//
//   2. Load a new model (weights + biases + shifts), see ns_loader.v
//   PC  -> FPGA : 0xC3  201 image bytes  CRC_hi  CRC_lo      (204 bytes)
//   FPGA -> PC  : 0x3C  status  crc_lo  crc_hi  loads
//                 status 0 = loaded, 1 = CRC error, 2 = timeout (1 and 2 keep the old model)
//                 loads  = number of successful loads since power-up
//
//   3. Which model is running?
//   PC  -> FPGA : 0xC5
//   FPGA -> PC  : 0x5C  crc_lo  crc_hi  source  loads
//                 source 0 = built-in model from the bitstream (crc reads 0000),
//                        1 = uploaded model (crc = its CRC-16)
//
//   If more than ~10 ms passes in the middle of a frame, the receiver drops the
//   partial frame and waits for a new header, so it can never get stuck.
//   An uploaded model lives in registers: it is lost at power-off (the built-in
//   model comes back), exactly like SRAM programming of the bitstream.
//
// LEDs (active low on the board):
//   LED0 heartbeat   LED1 toggles on every answer   LED2 last answer HEALTHY
//   LED3 last answer FAULT   LED4 uploaded model running   LED5 frame/CRC error seen
// =============================================================================
module tangnano20k_uart #(
    parameter CLKS_PER_BIT = 234,          // 27 MHz / 115200
    parameter TIMEOUT      = 270000        // ~10 ms at 27 MHz
)(
    input  wire       clk,                 // 27 MHz, pin 4
    input  wire       btn_s1,              // pin 88 (unused here, kept for same pin file)
    input  wire       uart_rx,             // pin 70 <- PC
    output wire       uart_tx,             // pin 69 -> PC
    output wire [5:0] leds                 // pins 15..20, active low
);
    // ------------------------------------------------------------ UART receive
    wire       rx_valid;
    wire [7:0] rx_data;
    ns_uart_rx #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_rx (
        .clk(clk), .rx(uart_rx), .valid(rx_valid), .data(rx_data));

    // ------------------------------------------------------------ model loader
    wire        ld_active, ld_busy, ld_we, ld_done;
    wire [7:0]  ld_addr;
    wire [15:0] ld_data, ld_crc;
    wire [1:0]  ld_status;
    reg         ld_start = 0;
    ns_loader #(.TIMEOUT(TIMEOUT)) u_ld (
        .clk(clk), .start(ld_start), .rx_valid(rx_valid), .rx_data(rx_data),
        .active(ld_active), .busy(ld_busy),
        .param_we(ld_we), .param_addr(ld_addr), .param_data(ld_data),
        .done(ld_done), .status(ld_status), .image_crc(ld_crc));

    reg  [15:0] model_crc = 0;             // CRC of the running model (0 = built-in)
    reg         model_src = 0;             // 0 built-in, 1 uploaded
    reg  [7:0]  loads     = 0;
    always @(posedge clk)
        if (ld_done && ld_status == 2'd0) begin
            model_crc <= ld_crc; model_src <= 1'b1; loads <= loads + 1'b1;
        end

    // ------------------------------------------------------------ frame parser
    reg  [2:0]  nbytes  = 0;               // 0 = waiting for header, 1..4 = inputs received
    reg  [31:0] x_buf   = 0;
    reg  [31:0] x_in    = 0;
    reg         in_valid = 0;
    reg  [$clog2(TIMEOUT+1)-1:0] idle = 0;
    reg         frame_err = 0;
    reg         info_req  = 0;

    always @(posedge clk) begin
        in_valid <= 1'b0;
        ld_start <= 1'b0;
        info_req <= 1'b0;
        if (ld_done && ld_status != 2'd0) frame_err <= 1'b1;     // bad upload -> LED5
        if (ld_active || ld_busy || ld_start) begin
            // bytes belong to the model loader
        end else if (rx_valid) begin
            idle <= 0;
            if (nbytes == 0) begin
                if      (rx_data == 8'hA5) nbytes   <= 1;
                else if (rx_data == 8'hC3) ld_start <= 1'b1;
                else if (rx_data == 8'hC5) info_req <= 1'b1;
                else frame_err <= 1'b1;                       // stray byte outside a frame
            end else begin
                x_buf <= {rx_data, x_buf[31:8]};              // x0 first -> ends in [7:0]
                if (nbytes == 4) begin
                    x_in     <= {rx_data, x_buf[31:8]};
                    in_valid <= 1'b1;
                    nbytes   <= 0;
                end else nbytes <= nbytes + 1'b1;
            end
        end else if (nbytes != 0) begin
            if (idle == TIMEOUT) begin nbytes <= 0; frame_err <= 1'b1; idle <= 0; end
            else idle <= idle + 1'b1;
        end
    end

    // ------------------------------------------------------------ the neural network
    wire        out_valid, fault;
    wire [15:0] y_out;
    netsilcon_top #(.PHASES(2)) nn (
        .clk(clk), .in_valid(in_valid), .x_in(x_in),
        .out_valid(out_valid), .y_out(y_out), .fault(fault),
        .param_we(ld_we), .param_addr(ld_addr), .param_data(ld_data));

    // ------------------------------------------------------------ hardware latency counter
    reg [7:0] lat_cnt = 0, latency = 0;
    reg       timing  = 0;
    always @(posedge clk) begin
        if (in_valid) begin timing <= 1'b1; lat_cnt <= 8'd1; end
        else if (timing) lat_cnt <= lat_cnt + 1'b1;
        if (out_valid && timing) begin timing <= 1'b0; latency <= lat_cnt; end
    end

    // ------------------------------------------------------------ reply: 5 bytes
    reg  [39:0] reply = 0;
    reg  [2:0]  left  = 0;                 // bytes still to send
    reg         tx_start = 0;
    reg  [7:0]  tx_byte  = 0;
    reg         resp_pending = 0, ld_pending = 0, info_pending = 0;
    reg         last_fault = 0, beat = 0;
    wire        tx_busy;

    always @(posedge clk) begin
        tx_start <= 1'b0;
        if (out_valid) begin               // answer ready -> build reply next clock (latency settles)
            resp_pending <= 1'b1;
            last_fault   <= fault;
            beat         <= ~beat;
        end
        if (ld_done)  ld_pending   <= 1'b1;   // wait 1 clock so loads/model_crc are updated
        if (info_req) info_pending <= 1'b1;
        if (resp_pending && left == 0) begin
            reply        <= {latency, {7'd0, last_fault}, y_out[15:8], y_out[7:0], 8'h5A};
            left         <= 3'd5;
            resp_pending <= 1'b0;
        end else if (ld_pending && !ld_done && left == 0) begin
            reply        <= {loads, ld_crc[15:8], ld_crc[7:0], {6'd0, ld_status}, 8'h3C};
            left         <= 3'd5;
            ld_pending   <= 1'b0;
        end else if (info_pending && left == 0) begin
            reply        <= {loads, {7'd0, model_src}, model_crc[15:8], model_crc[7:0], 8'h5C};
            left         <= 3'd5;
            info_pending <= 1'b0;
        end else if (left != 0 && !tx_busy && !tx_start) begin
            tx_byte  <= reply[7:0];
            reply    <= {8'h00, reply[39:8]};
            tx_start <= 1'b1;
            left     <= left - 1'b1;
        end
    end

    ns_uart_tx #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_tx (
        .clk(clk), .start(tx_start), .data(tx_byte), .tx(uart_tx), .busy(tx_busy));

    // ------------------------------------------------------------ LEDs
    reg [24:0] hb = 0;
    always @(posedge clk) hb <= hb + 1'b1;
    reg answered = 0;
    always @(posedge clk) if (out_valid) answered <= 1'b1;
    assign leds = ~{frame_err, model_src, answered & last_fault, answered & ~last_fault, beat, hb[24]};
endmodule
