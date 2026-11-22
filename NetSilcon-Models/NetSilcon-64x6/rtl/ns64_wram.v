// =============================================================================
// NetSilcon-64x6 : weight + bias memory, 32 block RAMs of 1K x 16
//
//   RAM r holds lane 2r in bits 7:0 and lane 2r+1 in bits 15:8.
//   Address = {bank, word[8:0]}. One shared read address for all 32 RAMs, so
//   one read gives all 64 lanes their byte (rdata[j*8 +: 8] = lane j).
//   The write port writes one FULL 16-bit word (two lanes) per write: the loader
//   pairs neuron 2r and 2r+1 itself, so no byte enables are needed. It only
//   ever writes the bank that is not running.
//   Initial contents: gen/wmem_00.mem .. wmem_31.mem (built-in model in bank 0).
//   The read port is enabled only while the engine computes (re): reading all 32
//   RAMs on every idle clock cost an estimated ~129 mW (Gowin power report) and
//   is the main suspect for the UART reply damage seen on the board.
//
//   Coded as the plainest simple-dual-port RAM (no byte enables, no initial value
//   on the output register) plus syn_ramstyle = "block_ram", so that GowinSynthesis
//   maps it to BSRAM. (The first version with byte enables was built from LUTs by
//   GowinSynthesis, although yosys mapped it to BSRAM.)
// =============================================================================
module ns64_wram_blk #(parameter INIT = "wmem_00.mem") (
    input  wire        clk,
    input  wire        we,
    input  wire [9:0]  waddr,
    input  wire [15:0] wdata,
    input  wire        re,
    input  wire [9:0]  raddr,
    output reg  [15:0] rdata
);
    (* syn_ramstyle = "block_ram" *) reg [15:0] m [0:1023] /* synthesis syn_ramstyle = "block_ram" */;
    initial $readmemh(INIT, m);
    always @(posedge clk) if (we) m[waddr] <= wdata;
    always @(posedge clk) if (re) rdata <= m[raddr];        // read only while the engine runs
endmodule

module ns64_wram (
    input  wire         clk,
    // write port (loader): one RAM word = two lanes per write
    input  wire         we,
    input  wire [4:0]   wram,           // RAM 0..31 = lanes 2r, 2r+1
    input  wire [9:0]   waddr,          // {bank, word}
    input  wire [15:0]  wdata,          // {lane 2r+1, lane 2r}
    // read port (engine): all 64 lanes
    input  wire         re,             // read enable: 1 only while the engine computes (power)
    input  wire [9:0]   raddr,          // {bank, word}
    output wire [511:0] rdata
);
    genvar r;
    generate for (r = 0; r < 32; r = r + 1) begin : ram
        localparam [7:0] D1 = 48 + r / 10, D0 = 48 + r % 10;
        ns64_wram_blk #(.INIT({"wmem_", D1, D0, ".mem"})) u (
            .clk(clk), .we(we && wram == r), .waddr(waddr), .wdata(wdata),
            .re(re), .raddr(raddr), .rdata(rdata[r*16 +: 16]));
    end endgenerate
endmodule
