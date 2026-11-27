// =============================================================================
// NetSilcon-LM-0 memories (model built into the bitstream, read-only in LM-0)
//
//   nslm_wram : 32 block RAMs of 512 x 16. RAM r = lane 2r (bits 7:0), 2r+1 (15:8).
//               One shared read address -> rdata[j*8 +: 8] = lane j.
//               Contents gen/wmem_00.mem .. wmem_31.mem.
//   nslm_erom : embedding ROM, 512 x 8 (symbol * 8 + d), gen/emb.mem.
//   Both have a registered read (1 clock), read only while enabled (power).
// =============================================================================
module nslm_wram_blk #(parameter INIT = "wmem_00.mem") (
    input  wire        clk,
    input  wire        re,
    input  wire [8:0]  raddr,
    output reg  [15:0] rdata
);
    (* syn_ramstyle = "block_ram" *) reg [15:0] m [0:511] /* synthesis syn_ramstyle = "block_ram" */;
    initial $readmemh(INIT, m);
    always @(posedge clk) if (re) rdata <= m[raddr];
endmodule

module nslm_wram (
    input  wire         clk,
    input  wire         re,
    input  wire [8:0]   raddr,
    output wire [511:0] rdata
);
    genvar r;
    generate for (r = 0; r < 32; r = r + 1) begin : ram
        localparam [7:0] D1 = 48 + r / 10, D0 = 48 + r % 10;
        nslm_wram_blk #(.INIT({"wmem_", D1, D0, ".mem"})) u (
            .clk(clk), .re(re), .raddr(raddr), .rdata(rdata[r*16 +: 16]));
    end endgenerate
endmodule

module nslm_erom (
    input  wire       clk,
    input  wire       re,
    input  wire [8:0] addr,
    output reg  [7:0] data
);
    (* syn_ramstyle = "block_ram" *) reg [7:0] m [0:511] /* synthesis syn_ramstyle = "block_ram" */;
    initial $readmemh("emb.mem", m);
    always @(posedge clk) if (re) data <= m[addr];
endmodule
