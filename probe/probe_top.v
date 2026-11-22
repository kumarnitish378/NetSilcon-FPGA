// =============================================================================
// NetSilcon-64x6 STEP 0 RESOURCE PROBE  (not the real design)
//
// Answers three questions before any real RTL is written:
//   1. Do 64 independent 8x8 signed multipliers (one per MAC lane) fit the
//      GW2AR-18 DSP blocks, in yosys/nextpnr AND in Gowin EDA?
//   2. Are 32 weight RAMs of 1K x 16 with BYTE-ENABLE writes inferred as BSRAM?
//   3. Is $readmemh initial content accepted for those BSRAMs?
//
// Structure: 32 RAMs (2 lanes each) share ONE read address. 64 lanes do
// acc += x * w every clock. x comes from an LFSR, writes come from a serial
// input pin, everything is XOR-reduced to an LED so nothing is optimised away.
// =============================================================================
module probe_wmem #(parameter INIT = "probe_w00.mem") (
    input  wire        clk,
    input  wire        we,
    input  wire [1:0]  be,
    input  wire [9:0]  waddr,
    input  wire [15:0] wdata,
    input  wire [9:0]  raddr,
    output reg  [15:0] rdata
);
    reg [15:0] m [0:1023];
    initial $readmemh(INIT, m);
    always @(posedge clk) begin
        if (we & be[0]) m[waddr][7:0]  <= wdata[7:0];
        if (we & be[1]) m[waddr][15:8] <= wdata[15:8];
        rdata <= m[raddr];
    end
endmodule

module probe_top (
    input  wire       clk,        // 27 MHz, pin 4
    input  wire       uart_rx,    // pin 70, used as a serial data source
    output wire       uart_tx,    // pin 69
    output wire [5:0] leds        // pins 15..20
);
    // ---------------- serial write path (keeps the RAM contents non-constant)
    reg [1:0]  s = 2'b11;
    reg [31:0] sh = 0;
    reg [5:0]  bc = 0;
    reg        we = 0;
    always @(posedge clk) begin
        s  <= {s[0], uart_rx};
        sh <= {sh[30:0], s[1]};
        bc <= bc + 1'b1;
        we <= (bc == 6'd63);
    end
    wire [4:0]  wblk  = sh[31:27];
    wire [9:0]  waddr = sh[25:16];
    wire [1:0]  be    = {sh[26], ~sh[26]};
    wire [15:0] wdata = {sh[7:0], sh[7:0]};

    // ---------------- shared read address + broadcast input
    reg [9:0] raddr = 0;
    reg [15:0] lfsr = 16'hACE1;
    always @(posedge clk) begin
        raddr <= raddr + 1'b1;
        lfsr  <= {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
    end
    reg signed [7:0] x_d = 0;               // aligned with RAM read latency
    always @(posedge clk) x_d <= lfsr[7:0];

    wire [64*24-1:0] accs;
    genvar b;
    generate for (b = 0; b < 32; b = b + 1) begin : blk
        wire [15:0] rd;
        localparam [7:0] D1 = 48 + b / 10, D0 = 48 + b % 10;
        probe_wmem #(.INIT({"probe_w", D1, D0, ".mem"})) u_m (
            .clk(clk), .we(we && wblk == b), .be(be), .waddr(waddr), .wdata(wdata),
            .raddr(raddr), .rdata(rd));
        genvar k;
        for (k = 0; k < 2; k = k + 1) begin : lane
            reg signed [15:0] p   = 0;      // product register
            reg signed [23:0] acc = 0;
            always @(posedge clk) begin
                p   <= x_d * $signed(rd[k*8 +: 8]);
                acc <= acc + {{8{p[15]}}, p};
            end
            assign accs[(b*2+k)*24 +: 24] = acc;
        end
    end endgenerate

    reg red = 0;
    always @(posedge clk) red <= ^accs;
    assign uart_tx = red;
    reg [24:0] hb = 0;
    always @(posedge clk) hb <= hb + 1'b1;
    assign leds = ~{5'd0, hb[24]};
endmodule
