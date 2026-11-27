// =============================================================================
// NetSilcon-LM-0 core: context register + engine + memories
//
//   push  : shift one symbol (0..41) into the 32-symbol context (newest in bits 5:0)
//   start : predict the next symbol from the current context
//   gen   : predict AND push the predicted symbol (one autoregressive step)
// push / start / gen are ignored while busy. The context starts as 32 newlines (0),
// exactly like nslm.LM.generate().
// =============================================================================
module nslm_core (
    input  wire         clk,
    input  wire         push,
    input  wire [5:0]   sym_in,
    input  wire         start,
    input  wire         gen,
    output wire         busy,
    output reg          done = 1'b0,     // 1-clock pulse after start/gen: next_sym valid
    output wire [5:0]   next_sym,
    output wire [335:0] logits,
    output wire [191:0] ctx
);
    `include "nslm_model.vh"

    reg  [191:0] ctx_r = 192'd0;
    assign ctx = ctx_r;
    reg          gen_r = 1'b0;
    wire         e_busy, e_done;
    wire [8:0]   raddr, eaddr;
    wire         ram_re;
    wire [511:0] rdata;
    wire [7:0]   edata;

    nslm_wram u_w (.clk(clk), .re(ram_re), .raddr(raddr), .rdata(rdata));
    nslm_erom u_e (.clk(clk), .re(ram_re), .addr(eaddr), .data(edata));
    nslm_engine u_eng (.clk(clk), .start((start || gen) && !e_busy), .ctx_in(ctx_r), .shifts(NSLM_SHIFTS),
                       .busy(e_busy), .done(e_done), .y_out(logits), .next_sym(next_sym),
                       .raddr(raddr), .ram_re(ram_re), .rdata(rdata), .eaddr(eaddr), .edata(edata));
    assign busy = e_busy || done;

    always @(posedge clk) begin
        done <= 1'b0;
        if (!e_busy) begin
            if (gen) gen_r <= 1'b1;
            else if (start) gen_r <= 1'b0;
            else if (push) ctx_r <= {ctx_r[185:0], sym_in};
        end
        if (e_done) begin
            done <= 1'b1;
            if (gen_r) ctx_r <= {ctx_r[185:0], next_sym};
        end
    end
endmodule
