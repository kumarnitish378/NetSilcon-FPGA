// =============================================================================
// NetSilcon model loader : receives a complete model over UART, checks its
// CRC, and only then copies it into the running network.
//
//   Model image = 201 bytes, then CRC-16 (2 bytes, high byte first):
//     bytes   0..143 : 144 weights        (int8)
//     bytes 144..195 : 26 biases          (int16, low byte first)
//     bytes 196..200 : 5 layer shifts     (0..15)
//   CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) over the 201 bytes.
//
//   Bytes go into a STAGING buffer first (it plays the role of the flash in
//   the final chip). The running model is not touched while loading, so a
//   broken or interrupted upload leaves the old model working.
//   Good CRC -> the staging buffer is copied through the param_* port
//   (201 clocks = 7.4 us at 27 MHz) and done/ok are pulsed.
//
//   status: 0 = loaded, 1 = CRC error (old model kept), 2 = timeout (old model kept)
// =============================================================================
module ns_loader #(
    parameter TIMEOUT = 270000              // clocks of silence that abort a load (~10 ms)
)(
    input  wire        clk,
    input  wire        start,               // 1-clock pulse: load header received
    input  wire        rx_valid,
    input  wire [7:0]  rx_data,
    output reg         active = 0,          // 1 while receiving (bytes belong to the loader)
    output reg         busy   = 0,          // 1 from start until done
    output reg         param_we   = 0,
    output reg  [7:0]  param_addr = 0,
    output reg  [15:0] param_data = 0,
    output reg         done   = 0,          // 1-clock pulse at the end
    output reg  [1:0]  status = 0,
    output reg  [15:0] image_crc = 0        // CRC of the received image
);
    localparam IMG = 201, TOTAL = 203;

    function [15:0] crc16(input [15:0] c, input [7:0] d);
        integer i;
        reg [15:0] x;
        begin
            x = c ^ {d, 8'h00};
            for (i = 0; i < 8; i = i + 1)
                x = x[15] ? ({x[14:0], 1'b0} ^ 16'h1021) : {x[14:0], 1'b0};
            crc16 = x;
        end
    endfunction

    reg [7:0]  stage [0:IMG-1];             // staging buffer (infers block/distributed RAM)
    reg [7:0]  cnt  = 0;                    // bytes received
    reg [15:0] crc  = 16'hFFFF;
    reg [18:0] idle = 0;
    reg        check = 0;

    // copy phase: read stage[p] (1 clock), then write it to the network
    reg        copying = 0, rd_v = 0;
    reg [7:0]  p = 0, p_q = 0;
    reg [7:0]  rd = 0, lo = 0;

    always @(posedge clk) begin
        done     <= 1'b0;
        param_we <= 1'b0;
        check    <= 1'b0;

        // ---------------- receive
        if (start) begin
            active <= 1'b1; busy <= 1'b1; cnt <= 0; crc <= 16'hFFFF; idle <= 0;
        end else if (active) begin
            if (rx_valid) begin
                idle <= 0;
                if (cnt < IMG) stage[cnt] <= rx_data;
                crc <= crc16(crc, rx_data);
                if (cnt == IMG - 1) image_crc <= crc16(crc, rx_data);
                cnt <= cnt + 1'b1;
                if (cnt == TOTAL - 1) begin active <= 1'b0; check <= 1'b1; end
            end else if (idle == TIMEOUT) begin
                active <= 1'b0; busy <= 1'b0; status <= 2'd2; done <= 1'b1;
            end else idle <= idle + 1'b1;
        end

        // ---------------- check: image + its own CRC leaves remainder 0
        if (check) begin
            if (crc == 16'h0000) begin copying <= 1'b1; p <= 0; end
            else begin busy <= 1'b0; status <= 2'd1; done <= 1'b1; end
        end

        // ---------------- copy staging -> network registers
        rd_v <= 1'b0;
        if (copying) begin
            rd   <= stage[p];
            p_q  <= p;
            rd_v <= 1'b1;
            if (p == IMG - 1) copying <= 1'b0;
            p <= p + 1'b1;
        end
        if (rd_v) begin
            if (p_q < 8'd144) begin                              // weight
                param_we <= 1'b1; param_addr <= p_q; param_data <= {8'h00, rd};
            end else if (p_q < 8'd196) begin                     // bias, two bytes
                if (!p_q[0]) lo <= rd;                           // 144 is even -> low byte
                else begin
                    param_we <= 1'b1; param_addr <= 8'd144 + ((p_q - 8'd145) >> 1);
                    param_data <= {rd, lo};
                end
            end else begin                                       // shift
                param_we <= 1'b1; param_addr <= p_q - 8'd26; param_data <= {12'h000, rd[3:0]};
            end
            if (p_q == IMG - 1) begin busy <= 1'b0; status <= 2'd0; done <= 1'b1; end
        end
    end
endmodule
