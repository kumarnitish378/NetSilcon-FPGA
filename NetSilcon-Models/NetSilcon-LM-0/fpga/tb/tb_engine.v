// =============================================================================
// tb_engine : NetSilcon-LM-0 engine vs the Python int8 model (bit-exact)
//   gen/test_ctx.mem    : N_VEC contexts (32 x 6 bit)
//   gen/test_logits.mem : expected {argmax, 42 logits}
//   Checks all 42 logits AND the argmax of every vector, measures the latency.
//   +n=<count> runs fewer vectors (used by the mutation test).
// =============================================================================
`timescale 1ns/1ps
module tb_engine;
    `include "num_vectors.vh"
    `include "nslm_model.vh"
    reg clk = 0;
    always #18.518 clk = ~clk;                       // 27 MHz

    reg          start = 0;
    reg  [191:0] ctx = 0;
    wire         busy, done;
    wire [335:0] y;
    wire [5:0]   nsym;
    wire [8:0]   raddr, eaddr;
    wire         re;
    wire [511:0] rdata;
    wire [7:0]   edata;
    nslm_wram u_w (.clk(clk), .re(re), .raddr(raddr), .rdata(rdata));
    nslm_erom u_e (.clk(clk), .re(re), .addr(eaddr), .data(edata));
    nslm_engine dut (.clk(clk), .start(start), .ctx_in(ctx), .shifts(NSLM_SHIFTS), .busy(busy), .done(done),
                     .y_out(y), .next_sym(nsym), .raddr(raddr), .ram_re(re), .rdata(rdata),
                     .eaddr(eaddr), .edata(edata));

    reg [191:0] tctx [0:N_VEC-1];
    reg [343:0] tout [0:N_VEC-1];
    integer k, cyc, errors = 0, shown = 0, lat_min = 99999, lat_max = 0, nv = N_VEC;
    initial begin
        $readmemh("test_ctx.mem", tctx);
        $readmemh("test_logits.mem", tout);
        if ($value$plusargs("n=%d", nv)) ;
        repeat (3) @(negedge clk);
        for (k = 0; k < nv; k = k + 1) begin
            ctx = tctx[k]; start = 1; @(negedge clk); start = 0; cyc = 1;
            while (!done) begin @(negedge clk); cyc = cyc + 1; end
            if (cyc < lat_min) lat_min = cyc;
            if (cyc > lat_max) lat_max = cyc;
            if (y !== tout[k][335:0] || nsym !== tout[k][341:336]) begin
                errors = errors + 1;
                if (shown < 4) begin
                    shown = shown + 1;
                    $display("MISMATCH #%0d argmax got %0d exp %0d\n  got %h\n  exp %h", k, nsym, tout[k][341:336], y, tout[k][335:0]);
                end
            end
            if (k % 200 == 0) $display("  ... %0d vectors, %0d mismatches", k + 1, errors);
        end
        $display("RESULT engine vectors=%0d mismatches=%0d latency=%0d..%0d clocks %s",
                 nv, errors, lat_min, lat_max, errors == 0 ? "PASS" : "FAIL");
        $finish;
    end
endmodule
