// =============================================================================
// NetSilcon-64x6 UART transmitter with the number of stop bits selectable at
// run time (stop2 = 0: 1 stop bit, exactly like ns_uart_tx of NetSilcon-6x4;
// stop2 = 1: 2 stop bits). Used for the link diagnosis (D1 command): the 64x6
// bitstream showed reply damage that the 6x4 bitstream does not show on the
// same board, PC and cable.
// =============================================================================
module ns64_uart_tx #(parameter CLKS_PER_BIT = 234) (
    input  wire       clk,
    input  wire       start,       // 1-clock pulse, ignored while busy
    input  wire [7:0] data,
    input  wire       stop2,       // sampled at start
    output reg        tx = 1'b1,
    output wire       busy
);
    reg [10:0] sh   = 11'h7FF;
    reg [3:0]  bitn = 4'd0;
    reg [3:0]  last = 4'd9;
    reg [15:0] cnt  = 16'd0;
    reg        act  = 1'b0;
    assign busy = act;
    always @(posedge clk) begin
        if (!act) begin
            tx <= 1'b1;
            if (start) begin
                sh <= {2'b11, data, 1'b0}; act <= 1'b1; bitn <= 4'd0; cnt <= 16'd0;
                last <= stop2 ? 4'd10 : 4'd9;
            end
        end else begin
            tx <= sh[0];
            if (cnt == CLKS_PER_BIT - 1) begin
                cnt <= 16'd0; sh <= {1'b1, sh[10:1]}; bitn <= bitn + 4'd1;
                if (bitn == last) act <= 1'b0;
            end else cnt <= cnt + 16'd1;
        end
    end
endmodule
