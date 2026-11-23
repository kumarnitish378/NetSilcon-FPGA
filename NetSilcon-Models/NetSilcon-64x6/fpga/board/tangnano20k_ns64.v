// =============================================================================
// NetSilcon-64x6 on Sipeed Tang Nano 20K : live inference + model update over USB serial
//
// 115200 baud 8N1 through the board's USB-C (BL616) serial port. All multi-byte
// numbers little endian.
//
//   1. Inference
//      PC  -> FPGA : A5  x0 .. x15                       (17 bytes, each x = 0..127)
//      FPGA -> PC  : 5A  y0 .. y15  argmax  lat_lo lat_hi (20 bytes)
//                    y = signed int8, argmax = index of the largest y (first one on ties),
//                    lat = clocks from engine start to result, counted in hardware
//   2. Load a model (see ns64_loader.v)
//      PC  -> FPGA : C3  23,335-byte image  CRC-32 (4)   (23,340 bytes)
//      FPGA -> PC  : 3C  status  crc32 (4)  loads         (7 bytes)
//                    status 0 loaded, 1 CRC error, 2 timeout, 3 shift > 23
//                    crc32 = CRC-32 the FPGA computed over the image it received
//                    (for status 2 it is the value of the previous upload)
//   3. Which model is running?
//      PC  -> FPGA : C5
//      FPGA -> PC  : 5C  crc32 (4)  source  loads         (7 bytes)
//                    source 0 = built-in model (crc32 = its CRC-32), 1 = uploaded
//
//   4. Link diagnosis: D1 s d -> 1D s d (stop bits / reply delay), D2 n k -> 2D + n pattern
//      bytes. See the replies section below.
//
//   A frame that stalls for ~10 ms is dropped (the receiver waits for a new header).
//   Uploaded models live in block RAM: lost at power-off, the built-in model returns.
//
// LEDs (active low): LED0 heartbeat, LED1 toggles on every answer, LED2 upload in
//   progress, LED3 bank 1 active, LED4 uploaded model running, LED5 frame/CRC error seen.
// =============================================================================
module tangnano20k_ns64 #(
    parameter CLKS_PER_BIT = 234,          // 27 MHz / 115200
    parameter TIMEOUT      = 270000,       // ~10 ms at 27 MHz
    parameter WITH_ENGINE  = 1             // 0 = link diagnosis build: no engine, no weight RAM;
                                           //     an inference echoes x0..x15 after 448 clocks
)(
    input  wire       clk,                 // 27 MHz, pin 4
    input  wire       uart_rx,             // pin 70 <- PC
    output wire       uart_tx,             // pin 69 -> PC
    output wire [5:0] leds                 // pins 15..20, active low
);
    `include "ns64_builtin.vh"

    // ------------------------------------------------------------ UART receive
    wire       rx_valid;
    wire [7:0] rx_data;
    ns_uart_rx #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_rx (
        .clk(clk), .rx(uart_rx), .valid(rx_valid), .data(rx_data));

    // ------------------------------------------------------------ model state
    reg         bank      = 1'b0;          // active weight-RAM bank
    reg  [34:0] shifts    = BUILTIN_SHIFTS;
    reg  [31:0] model_crc = BUILTIN_CRC32;
    reg         model_src = 1'b0;          // 0 built-in, 1 uploaded
    reg  [7:0]  loads     = 8'd0;

    // ------------------------------------------------------------ loader
    wire        ld_active, ld_busy, ld_we, ld_done, ld_swap;
    wire [4:0]  ld_ram;
    wire [9:0]  ld_addr;
    wire [15:0] ld_data;
    wire [34:0] ld_shifts;
    wire [1:0]  ld_status;
    wire [31:0] ld_crc;
    reg         ld_start = 1'b0;
    ns64_loader #(.TIMEOUT(TIMEOUT)) u_ld (
        .clk(clk), .start(ld_start), .rx_valid(rx_valid), .rx_data(rx_data),
        .active_bank(bank), .active(ld_active), .busy(ld_busy),
        .wr_we(ld_we), .wr_ram(ld_ram), .wr_addr(ld_addr), .wr_data(ld_data),
        .new_shifts(ld_shifts), .done(ld_done), .swap(ld_swap),
        .status(ld_status), .image_crc(ld_crc));

    wire eng_busy, eng_start;              // engine handshake (driven below)

    // ------------------------------------------------------------ frame parser
    reg  [4:0]   nbytes = 5'd0;            // 0 = waiting for header, 1..16 = inputs received
    reg  [127:0] x_buf  = 128'd0;
    reg          x_ready = 1'b0;           // a complete input frame waits for the engine
    reg  [$clog2(TIMEOUT+1)-1:0] idle = 0;
    reg          frame_err = 1'b0;
    reg          info_req  = 1'b0;
    reg  [7:0]   hdr       = 8'h00;        // header of the frame being received (A5, D1, D2)
    reg  [7:0]   dbg_b0    = 8'd0;
    reg          dbg_set_req = 1'b0, dbg_pat_req = 1'b0;
    reg  [7:0]   dbg_a = 8'd0, dbg_b = 8'd0;   // the two payload bytes of a D1 / D2 frame

    always @(posedge clk) begin
        ld_start <= 1'b0;
        info_req <= 1'b0;
        dbg_set_req <= 1'b0;
        dbg_pat_req <= 1'b0;
        if (ld_done && ld_status != 2'd0) frame_err <= 1'b1;
        if (ld_active || ld_busy || ld_start) begin
            // bytes belong to the model loader
        end else if (rx_valid) begin
            idle <= 0;
            if (nbytes == 5'd0) begin
                if      (rx_data == 8'hA5) begin nbytes <= 5'd1; hdr <= rx_data; end
                else if (rx_data == 8'hD1 || rx_data == 8'hD2) begin nbytes <= 5'd1; hdr <= rx_data; end
                else if (rx_data == 8'hC3) ld_start <= 1'b1;
                else if (rx_data == 8'hC5) info_req <= 1'b1;
                else frame_err <= 1'b1;                            // stray byte
            end else if (hdr != 8'hA5) begin                       // D1 / D2: 2 payload bytes
                if (nbytes == 5'd1) begin dbg_b0 <= rx_data; nbytes <= 5'd2; end
                else begin
                    dbg_a <= dbg_b0; dbg_b <= rx_data; nbytes <= 5'd0;
                    if (hdr == 8'hD1) dbg_set_req <= 1'b1; else dbg_pat_req <= 1'b1;
                end
            end else begin
                x_buf <= {rx_data, x_buf[127:8]};                  // x0 first -> ends in [7:0]
                if (nbytes == 5'd16) begin x_ready <= 1'b1; nbytes <= 5'd0; end
                else nbytes <= nbytes + 5'd1;
            end
        end else if (nbytes != 5'd0) begin
            if (idle == TIMEOUT) begin nbytes <= 5'd0; frame_err <= 1'b1; idle <= 0; end
            else idle <= idle + 1'b1;
        end
        if (eng_start) x_ready <= 1'b0;
    end

    // ------------------------------------------------------------ bank swap
    // the swap waits until the engine is idle, and the engine waits for the swap
    reg swap_pending = 1'b0;
    always @(posedge clk) begin
        if (ld_swap) swap_pending <= 1'b1;
        else if (swap_pending && !eng_busy) begin
            swap_pending <= 1'b0;
            bank      <= ~bank;
            shifts    <= ld_shifts;
            model_crc <= ld_crc;
            model_src <= 1'b1;
            loads     <= loads + 8'd1;
        end
    end

    // ------------------------------------------------------------ engine + weight RAM
    assign       eng_start = x_ready && !eng_busy && !swap_pending && !ld_swap;
    wire         eng_done;
    wire [127:0] y_out;
    wire [8:0]   eng_raddr;
    wire         eng_re;
    wire [511:0] rdata;
    generate if (WITH_ENGINE) begin : g_eng
        ns64_wram u_ram (.clk(clk), .we(ld_we), .wram(ld_ram), .waddr(ld_addr), .wdata(ld_data),
                         .re(eng_re), .raddr({bank, eng_raddr}), .rdata(rdata));
        ns64_engine u_eng (.clk(clk), .start(eng_start), .x_in(x_buf), .shifts(shifts),
                           .busy(eng_busy), .done(eng_done), .y_out(y_out),
                           .raddr(eng_raddr), .ram_re(eng_re), .rdata(rdata));
    end else begin : g_echo
        // stand-in with the same handshake and timing: busy 448 clocks, then y = x
        reg         e_busy = 1'b0, e_done = 1'b0;
        reg [8:0]   e_cnt  = 9'd0;
        reg [127:0] e_y    = 128'd0;
        always @(posedge clk) begin
            e_done <= 1'b0;
            if (eng_start && !e_busy) begin e_busy <= 1'b1; e_cnt <= 9'd1; e_y <= x_buf; end
            else if (e_busy) begin
                e_cnt <= e_cnt + 9'd1;
                if (e_cnt == 9'd447) begin e_busy <= 1'b0; e_done <= 1'b1; end
            end
        end
        assign eng_busy = e_busy;
        assign eng_done = e_done;
        assign y_out    = e_y;
        assign eng_raddr = 9'd0;
        assign eng_re    = 1'b0;
        assign rdata     = 512'd0;
    end endgenerate

    // ------------------------------------------------------------ hardware latency counter
    reg [15:0] lat_cnt = 16'd0, latency = 16'd0;
    always @(posedge clk) begin
        if (eng_start) lat_cnt <= 16'd1;
        else if (eng_busy) lat_cnt <= lat_cnt + 16'd1;
        if (eng_done) latency <= lat_cnt;
    end

    // ------------------------------------------------------------ argmax (16 clocks after done)
    reg [127:0] y_hold = 128'd0;
    reg  [4:0]  am_i = 5'd0;
    reg         am_run = 1'b0, am_done = 1'b0;
    reg  [3:0]  am_idx = 4'd0;
    reg  signed [7:0] am_max = 8'sd0;
    wire signed [7:0] y_i = y_hold[am_i[3:0]*8 +: 8];
    always @(posedge clk) begin
        am_done <= 1'b0;
        if (eng_done) begin
            y_hold <= y_out; am_run <= 1'b1; am_i <= 5'd0;
        end else if (am_run) begin
            if (am_i == 5'd0 || y_i > am_max) begin am_max <= y_i; am_idx <= am_i[3:0]; end
            if (am_i == 5'd15) begin am_run <= 1'b0; am_done <= 1'b1; end
            am_i <= am_i + 5'd1;
        end
    end

    // ------------------------------------------------------------ replies
    // Link diagnosis (UART bytes, all replies are fixed length):
    //   D1 s d  -> 1D s d     s: 0 = 1 stop bit, 1 = 2 stop bits; d: wait d*256 clocks
    //                         (9.5 us per step at 27 MHz) before the first byte of every reply.
    //                         Power-up: 1 stop bit, no wait (same as NetSilcon-6x4).
    //   D2 n k  -> 2D + n pattern bytes   k: 0 = 00, 1 = FF, 2 = 0,1,2,..., 3 = 55
    reg  [159:0] reply = 160'd0;
    reg  [4:0]   left  = 5'd0;             // bytes still to send from `reply`
    reg  [7:0]   pat_left = 8'd0;          // pattern bytes still to send after the reply
    reg  [7:0]   pat_i    = 8'd0;
    reg  [1:0]   pat_kind = 2'd0;
    reg          tx_stop2 = 1'b0;
    reg  [7:0]   tx_dly   = 8'd0;
    reg  [15:0]  gap      = 16'd0;         // wait before the first byte of a reply
    reg          tx_start = 1'b0;
    reg  [7:0]   tx_byte  = 8'd0;
    reg          resp_pending = 1'b0, ld_pending = 1'b0, info_pending = 1'b0;
    reg          set_pending = 1'b0, pat_pending = 1'b0;
    reg          beat = 1'b0;
    wire         tx_busy;
    wire         idle_tx = (left == 5'd0) && (pat_left == 8'd0);
    wire [7:0]   pat_byte = (pat_kind == 2'd0) ? 8'h00 : (pat_kind == 2'd1) ? 8'hFF :
                            (pat_kind == 2'd2) ? pat_i : 8'h55;

    always @(posedge clk) begin
        tx_start <= 1'b0;
        if (gap != 16'd0) gap <= gap - 16'd1;
        if (am_done)  begin resp_pending <= 1'b1; beat <= ~beat; end
        if (ld_done)  ld_pending   <= 1'b1;
        if (info_req) info_pending <= 1'b1;
        if (dbg_set_req) begin set_pending <= 1'b1; tx_stop2 <= dbg_a[0]; tx_dly <= dbg_b; end
        if (dbg_pat_req) pat_pending <= 1'b1;
        if (resp_pending && idle_tx) begin
            reply <= {latency, 4'd0, am_idx, y_hold, 8'h5A};
            left  <= 5'd20; gap <= {tx_dly, 8'd0};
            resp_pending <= 1'b0;
        end else if (ld_pending && !ld_done && !ld_swap && !swap_pending && idle_tx) begin
            reply <= {104'd0, loads, ld_crc, {6'd0, ld_status}, 8'h3C};
            left  <= 5'd7; gap <= {tx_dly, 8'd0};
            ld_pending <= 1'b0;
        end else if (info_pending && !swap_pending && idle_tx) begin
            reply <= {104'd0, loads, {7'd0, model_src}, model_crc, 8'h5C};
            left  <= 5'd7; gap <= {tx_dly, 8'd0};
            info_pending <= 1'b0;
        end else if (set_pending && idle_tx) begin
            reply <= {136'd0, tx_dly, {7'd0, tx_stop2}, 8'h1D};
            left  <= 5'd3; gap <= {tx_dly, 8'd0};
            set_pending <= 1'b0;
        end else if (pat_pending && idle_tx) begin
            reply <= {152'd0, 8'h2D};
            left  <= 5'd1; gap <= {tx_dly, 8'd0};
            pat_left <= dbg_a; pat_kind <= dbg_b[1:0]; pat_i <= 8'd0;
            pat_pending <= 1'b0;
        end else if (gap == 16'd0 && !tx_busy && !tx_start) begin
            if (left != 5'd0) begin
                tx_byte  <= reply[7:0];
                reply    <= {8'h00, reply[159:8]};
                tx_start <= 1'b1;
                left     <= left - 5'd1;
            end else if (pat_left != 8'd0) begin
                tx_byte  <= pat_byte;
                tx_start <= 1'b1;
                pat_left <= pat_left - 8'd1;
                pat_i    <= pat_i + 8'd1;
            end
        end
    end

    ns64_uart_tx #(.CLKS_PER_BIT(CLKS_PER_BIT)) u_tx (
        .clk(clk), .start(tx_start), .data(tx_byte), .stop2(tx_stop2), .tx(uart_tx), .busy(tx_busy));

    // ------------------------------------------------------------ LEDs
    reg [24:0] hb = 25'd0;
    always @(posedge clk) hb <= hb + 25'd1;
    assign leds = ~{frame_err, model_src, bank, ld_busy, beat, hb[24]};
endmodule
