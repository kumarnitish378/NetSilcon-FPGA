// =============================================================================
// NetSilcon-64x6 model loader: receives a complete model over UART, writes it
// straight into the INACTIVE weight-RAM bank, checks CRC-32, and only then
// asks the top to swap banks (1 clock). The running model is never touched.
//
//   Wire format after the C3 header (23,339 bytes):
//     bytes      0 .. 22527 : weights, int8. Layer by layer; inside a layer
//                             neuron j, input i at j*N_in + i
//     bytes  22528 .. 23327 : 400 biases, int16 little endian, layer by layer
//     bytes  23328 .. 23334 : 7 layer shifts, 0..23
//     bytes  23335 .. 23338 : CRC-32 of bytes 0..23334, little endian
//   CRC-32 = IEEE 802.3 / zlib.crc32 (reflected, poly 0xEDB88320,
//            init 0xFFFFFFFF, final XOR 0xFFFFFFFF).
//
//   RAM placement (see model/ns64.py): lane j column, word base[l] + 2 + i for
//   weights, base[l] + 0/1 for bias low/high byte; bank = NOT active_bank.
//   Lanes 2r and 2r+1 share one 16-bit RAM word. The bytes of the even neuron
//   are held in a 64-byte pair buffer; when the same byte of the odd neuron
//   arrives, the full word {odd, even} is written (no byte enables needed).
//
//   status: 0 = loaded (swap pulsed), 1 = CRC error, 2 = timeout (frame
//           incomplete), 3 = CRC good but a shift is > 23.  For 1..3 the old
//           model keeps running (the inactive bank holds junk, never used).
// =============================================================================
module ns64_loader #(
    parameter TIMEOUT = 270000              // clocks of silence that abort a load (~10 ms)
)(
    input  wire        clk,
    input  wire        start,               // 1-clock pulse: C3 header received
    input  wire        rx_valid,
    input  wire [7:0]  rx_data,
    input  wire        active_bank,
    output reg         active = 1'b0,       // 1 while receiving (bytes belong to the loader)
    output reg         busy   = 1'b0,       // 1 from start until done
    output reg         wr_we   = 1'b0,
    output reg  [4:0]  wr_ram  = 5'd0,      // RAM r = lanes 2r, 2r+1
    output reg  [9:0]  wr_addr = 10'd0,     // {bank, word}
    output reg  [15:0] wr_data = 16'd0,     // {lane 2r+1, lane 2r}
    output reg  [34:0] new_shifts = 35'd0,
    output reg         done   = 1'b0,       // 1-clock pulse at the end
    output reg         swap   = 1'b0,       // 1-clock pulse with done when status = 0
    output reg  [1:0]  status = 2'd0,
    output reg  [31:0] image_crc = 32'd0    // CRC-32 of the received image
);
    localparam P_W = 2'd0, P_B = 2'd1, P_S = 2'd2, P_C = 2'd3;

    function [31:0] crc32_byte(input [31:0] c, input [7:0] d);
        integer k;
        reg [31:0] x;
        begin
            x = c ^ {24'd0, d};
            for (k = 0; k < 8; k = k + 1)
                x = x[0] ? ((x >> 1) ^ 32'hEDB88320) : (x >> 1);
            crc32_byte = x;
        end
    endfunction

    reg [1:0]  ph   = P_W;
    reg [2:0]  l    = 3'd0;                 // layer 0..6 (also shift index)
    reg [5:0]  j    = 6'd0;                 // neuron
    reg [5:0]  i    = 6'd0;                 // input
    reg        bsel = 1'b0;                 // bias byte 0 = low, 1 = high
    reg [1:0]  cc   = 2'd0;                 // CRC byte counter
    reg [31:0] crc  = 32'hFFFFFFFF;
    reg [31:0] rx_crc = 32'd0;
    reg        bad_shift = 1'b0;
    reg [18:0] idle = 19'd0;
    reg        check = 1'b0;
    reg [7:0]  pbuf [0:63];                 // pair buffer: even neuron's bytes (weights; biases use 0/1)

    wire [5:0] last_i = (l == 3'd0) ? 6'd15 : 6'd63;
    wire [5:0] last_j = (l == 3'd6) ? 6'd15 : 6'd63;
    wire [8:0] base = (l == 3'd0) ? 9'd0   : (l == 3'd1) ? 9'd18  :
                      (l == 3'd2) ? 9'd84  : (l == 3'd3) ? 9'd150 :
                      (l == 3'd4) ? 9'd216 : (l == 3'd5) ? 9'd282 : 9'd348;

    always @(posedge clk) begin
        done  <= 1'b0;
        swap  <= 1'b0;
        wr_we <= 1'b0;
        check <= 1'b0;

        if (start) begin
            active <= 1'b1; busy <= 1'b1; idle <= 19'd0;
            ph <= P_W; l <= 3'd0; j <= 6'd0; i <= 6'd0; bsel <= 1'b0; cc <= 2'd0;
            crc <= 32'hFFFFFFFF; bad_shift <= 1'b0;
        end else if (active) begin
            if (rx_valid) begin
                idle <= 19'd0;
                if (ph != P_C) crc <= crc32_byte(crc, rx_data);
                case (ph)
                    P_W: begin
                        if (!j[0]) pbuf[i] <= rx_data;          // even neuron: hold
                        else begin                                // odd neuron: write the pair
                            wr_we <= 1'b1; wr_ram <= j[5:1]; wr_data <= {rx_data, pbuf[i]};
                            wr_addr <= {~active_bank, base + 9'd2 + {3'd0, i}};
                        end
                        if (i == last_i) begin
                            i <= 6'd0;
                            if (j == last_j) begin
                                j <= 6'd0;
                                if (l == 3'd6) begin l <= 3'd0; ph <= P_B; end
                                else l <= l + 3'd1;
                            end else j <= j + 6'd1;
                        end else i <= i + 6'd1;
                    end
                    P_B: begin
                        if (!j[0]) pbuf[{5'd0, bsel}] <= rx_data;
                        else begin
                            wr_we <= 1'b1; wr_ram <= j[5:1]; wr_data <= {rx_data, pbuf[{5'd0, bsel}]};
                            wr_addr <= {~active_bank, base + {8'd0, bsel}};
                        end
                        bsel <= ~bsel;
                        if (bsel) begin
                            if (j == last_j) begin
                                j <= 6'd0;
                                if (l == 3'd6) begin l <= 3'd0; ph <= P_S; end
                                else l <= l + 3'd1;
                            end else j <= j + 6'd1;
                        end
                    end
                    P_S: begin
                        new_shifts[l*5 +: 5] <= rx_data[4:0];
                        if (rx_data > 8'd23) bad_shift <= 1'b1;
                        if (l == 3'd6) begin l <= 3'd0; ph <= P_C; end
                        else l <= l + 3'd1;
                    end
                    default: begin                              // P_C: CRC, little endian
                        rx_crc <= {rx_data, rx_crc[31:8]};
                        cc <= cc + 2'd1;
                        if (cc == 2'd3) begin active <= 1'b0; check <= 1'b1; end
                    end
                endcase
            end else if (idle == TIMEOUT) begin
                active <= 1'b0; busy <= 1'b0; status <= 2'd2; done <= 1'b1;
            end else idle <= idle + 19'd1;
        end

        if (check) begin
            image_crc <= ~crc;
            busy <= 1'b0; done <= 1'b1;
            if (~crc != rx_crc)  status <= 2'd1;
            else if (bad_shift)  status <= 2'd3;
            else begin           status <= 2'd0; swap <= 1'b1; end
        end
    end
endmodule
