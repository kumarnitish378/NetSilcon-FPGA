// =============================================================================
// NetSilcon UART helpers (8N1). Unique module names so they never clash with
// the uart_tx inside tangnano20k_selftest.v when both files are in one project.
// =============================================================================

// ----------------------------------------------------------------- receiver
module ns_uart_rx #(parameter CLKS_PER_BIT = 234) (
    input  wire       clk,
    input  wire       rx,          // idle high
    output reg        valid = 0,   // 1-clock pulse when a byte is ready
    output reg  [7:0] data  = 0
);
    reg [1:0]  sync = 2'b11;       // 2-flop synchronizer (rx is asynchronous)
    reg [15:0] cnt  = 0;
    reg [3:0]  bitn = 0;
    reg [7:0]  sh   = 0;
    reg [1:0]  st   = 0;           // 0 idle, 1 start, 2 data, 3 stop
    wire       r = sync[1];

    always @(posedge clk) begin
        sync  <= {sync[0], rx};
        valid <= 1'b0;
        case (st)
            0: if (!r) begin st <= 1; cnt <= 0; end                 // falling edge = start bit
            1: if (cnt == CLKS_PER_BIT/2 - 1) begin                  // middle of start bit
                   cnt <= 0;
                   if (!r) begin st <= 2; bitn <= 0; end else st <= 0;   // glitch -> back to idle
               end else cnt <= cnt + 1'b1;
            2: if (cnt == CLKS_PER_BIT - 1) begin                    // middle of each data bit
                   cnt <= 0; sh <= {r, sh[7:1]}; bitn <= bitn + 1'b1;
                   if (bitn == 7) st <= 3;
               end else cnt <= cnt + 1'b1;
            3: if (cnt == CLKS_PER_BIT - 1) begin                    // middle of stop bit
                   st <= 0; cnt <= 0;
                   if (r) begin valid <= 1'b1; data <= sh; end       // good stop bit -> accept
               end else cnt <= cnt + 1'b1;
        endcase
    end
endmodule

// ----------------------------------------------------------------- transmitter
module ns_uart_tx #(parameter CLKS_PER_BIT = 234) (
    input  wire       clk,
    input  wire       start,       // 1-clock pulse, ignored while busy
    input  wire [7:0] data,
    output reg        tx = 1'b1,
    output wire       busy
);
    reg [9:0]  sh  = 10'h3FF;
    reg [3:0]  bitn = 0;
    reg [15:0] cnt = 0;
    reg        act = 0;
    assign busy = act;
    always @(posedge clk) begin
        if (!act) begin
            tx <= 1'b1;
            if (start) begin sh <= {1'b1, data, 1'b0}; act <= 1'b1; bitn <= 0; cnt <= 0; end
        end else begin
            tx <= sh[0];
            if (cnt == CLKS_PER_BIT - 1) begin
                cnt <= 0; sh <= {1'b1, sh[9:1]}; bitn <= bitn + 1'b1;
                if (bitn == 9) act <= 1'b0;
            end else cnt <= cnt + 1'b1;
        end
    end
endmodule
