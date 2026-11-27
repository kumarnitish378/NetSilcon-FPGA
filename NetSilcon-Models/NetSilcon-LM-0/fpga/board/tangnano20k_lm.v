// =============================================================================
// NetSilcon-LM-0 on the Tang Nano 20K: chat with the FPGA over the USB serial port
//   115200 8N1. Type a line and press Enter, e.g.   q: is the pump running?
//   The FPGA echoes what it understood (lower case), then writes its own answer
//   line, one character per model step, generated on the chip, until it outputs a
//   newline (or 63 characters).
//
//   Byte -> symbol: a-z, A-Z (made lower case), 0-9, space : , . ?   CR or LF = newline
//   (LF right after CR is skipped). Other bytes are ignored. Bytes that arrive while
//   the FPGA is answering are dropped.
//   Newline is sent as CR LF.  LED0 (active low) = answering.
// =============================================================================
module tangnano20k_lm (
    input  wire       clk,        // 27 MHz
    input  wire       uart_rx,
    output wire       uart_tx,
    output wire [5:0] leds
);
    // ------------------------------------------------------------ UART
    wire       rx_valid; wire [7:0] rx_data;
    ns_uart_rx #(.CLKS_PER_BIT(234)) u_rx (.clk(clk), .rx(uart_rx), .valid(rx_valid), .data(rx_data));
    reg        tx_start = 1'b0; reg [7:0] tx_data = 8'd0; wire tx_busy;
    ns_uart_tx #(.CLKS_PER_BIT(234)) u_tx (.clk(clk), .start(tx_start), .data(tx_data), .tx(uart_tx), .busy(tx_busy));

    // ------------------------------------------------------------ TX FIFO (16 bytes)
    reg [7:0] fifo [0:15];
    reg [3:0] wp = 4'd0, rp = 4'd0;
    reg [4:0] fill = 5'd0;
    reg       wr = 1'b0; reg [7:0] wdata = 8'd0;
    reg       wr2 = 1'b0; reg [7:0] wdata2 = 8'd0;      // second byte (CR LF)
    wire      rd = !tx_busy && !tx_start && fill != 5'd0;
    always @(posedge clk) begin
        tx_start <= 1'b0;
        if (rd) begin tx_data <= fifo[rp]; tx_start <= 1'b1; rp <= rp + 4'd1; end
        if (wr && wr2) begin fifo[wp] <= wdata; fifo[wp + 4'd1] <= wdata2; wp <= wp + 4'd2; end
        else if (wr)   begin fifo[wp] <= wdata; wp <= wp + 4'd1; end
        fill <= fill + (wr ? (wr2 ? 5'd2 : 5'd1) : 5'd0) - (rd ? 5'd1 : 5'd0);
    end

    // ------------------------------------------------------------ symbol maps
    function [6:0] to_sym;                // bit 6 = valid
        input [7:0] b;
        begin
            if (b == 8'h0D || b == 8'h0A)         to_sym = 7'h40 | 7'd0;
            else if (b == " ")                    to_sym = 7'h40 | 7'd1;
            else if (b == ":")                    to_sym = 7'h40 | 7'd2;
            else if (b == ",")                    to_sym = 7'h40 | 7'd3;
            else if (b == ".")                    to_sym = 7'h40 | 7'd4;
            else if (b == "?")                    to_sym = 7'h40 | 7'd5;
            else if (b >= "a" && b <= "z")        to_sym = 7'h40 | (b - "a" + 7'd6);
            else if (b >= "A" && b <= "Z")        to_sym = 7'h40 | (b - "A" + 7'd6);
            else if (b >= "0" && b <= "9")        to_sym = 7'h40 | (b - "0" + 7'd32);
            else                                  to_sym = 7'd0;
        end
    endfunction
    function [7:0] to_ascii;
        input [5:0] s;
        begin
            case (s)
                6'd0: to_ascii = 8'h0A; 6'd1: to_ascii = " "; 6'd2: to_ascii = ":";
                6'd3: to_ascii = ",";   6'd4: to_ascii = "."; 6'd5: to_ascii = "?";
                default: to_ascii = (s < 6'd32) ? ("a" + s - 6'd6) : ("0" + s - 6'd32);
            endcase
        end
    endfunction

    // ------------------------------------------------------------ model
    reg        push = 1'b0, gen = 1'b0; reg [5:0] psym = 6'd0;
    wire       busy, done; wire [5:0] nsym; wire [335:0] logits; wire [191:0] ctx;
    nslm_core u_lm (.clk(clk), .push(push), .sym_in(psym), .start(1'b0), .gen(gen), .busy(busy),
                    .done(done), .next_sym(nsym), .logits(logits), .ctx(ctx));

    localparam S_IDLE = 2'd0, S_GEN = 2'd1, S_WAIT = 2'd2, S_ROOM = 2'd3;
    reg [1:0] st = S_IDLE;
    reg       last_cr = 1'b0;
    reg [5:0] count = 6'd0;
    wire [6:0] rs = to_sym(rx_data);
    always @(posedge clk) begin
        push <= 1'b0; gen <= 1'b0; wr <= 1'b0; wr2 <= 1'b0;
        case (st)
            S_IDLE: if (rx_valid) begin
                last_cr <= (rx_data == 8'h0D);
                if (rs[6] && !(rx_data == 8'h0A && last_cr) && fill < 5'd14) begin
                    psym <= rs[5:0]; push <= 1'b1;
                    if (rs[5:0] == 6'd0) begin                    // Enter: echo CR LF, answer
                        wr <= 1'b1; wdata <= 8'h0D; wr2 <= 1'b1; wdata2 <= 8'h0A;
                        count <= 6'd0; st <= S_ROOM;
                    end else begin
                        wr <= 1'b1; wdata <= to_ascii(rs[5:0]);
                    end
                end
            end
            S_ROOM: if (fill < 5'd14 && !busy && !push) begin gen <= 1'b1; st <= S_GEN; end
            S_GEN:  st <= S_WAIT;                                 // core takes gen this clock
            S_WAIT: if (done) begin
                count <= count + 6'd1;
                if (nsym == 6'd0) begin                           // answer finished
                    wr <= 1'b1; wdata <= 8'h0D; wr2 <= 1'b1; wdata2 <= 8'h0A; st <= S_IDLE;
                end else if (count == 6'd62) begin                // 63 chars: end the line
                    wr <= 1'b1; wdata <= to_ascii(nsym); st <= S_IDLE;
                    psym <= 6'd0; push <= 1'b1;                   // and keep the context sane
                end else begin
                    wr <= 1'b1; wdata <= to_ascii(nsym); st <= S_ROOM;
                end
            end
        endcase
    end

    reg [23:0] blink = 24'd0;
    always @(posedge clk) blink <= blink + 24'd1;
    assign leds = ~{blink[23], 4'b0000, st != S_IDLE};            // LED5 = alive, LED0 = answering
endmodule
