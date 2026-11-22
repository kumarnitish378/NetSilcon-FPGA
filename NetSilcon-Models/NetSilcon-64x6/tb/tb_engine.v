// =============================================================================
// tb_engine : NetSilcon-64x6 engine vs the Python int8 model (bit-exact)
//
//   RAM bank 0 = synthetic model -> gen/test_in.mem   / test_out.mem   (1000 vectors)
//   RAM bank 1 = stress model    -> gen/stress_in.mem / stress_out.mem (200 vectors)
//   Uses gen/tb/wmem_XX.mem (both banks filled). Also measures the latency.
// =============================================================================
`timescale 1ns/1ps
module tb_engine;
    `include "num_vectors.vh"
    `include "ns64_builtin.vh"

    reg clk = 0;
    always #18.518 clk = ~clk;                       // 27 MHz

    reg          start = 0;
    reg  [127:0] x_in  = 0;
    reg  [34:0]  shifts = 0;
    reg          bank  = 0;
    wire         busy, done;
    wire [127:0] y_out;
    wire [8:0]   raddr;
    wire         ram_re;
    wire [511:0] rdata;

    ns64_wram u_ram (.clk(clk), .we(1'b0), .wram(5'd0), .waddr(10'd0), .wdata(16'd0),
                     .re(ram_re), .raddr({bank, raddr}), .rdata(rdata));
    ns64_engine dut (.clk(clk), .start(start), .x_in(x_in), .shifts(shifts),
                     .busy(busy), .done(done), .y_out(y_out), .raddr(raddr), .ram_re(ram_re), .rdata(rdata));

    reg [127:0] tin  [0:N_VEC-1];
    reg [127:0] tout [0:N_VEC-1];
    reg [127:0] sin  [0:N_STRESS-1];
    reg [127:0] sout [0:N_STRESS-1];
    integer errors = 0, total = 0, k, cyc, lat = 0, lat_min = 99999, lat_max = 0, shown = 0;
    integer nv = N_VEC, ns = N_STRESS;                // +n=<count> runs fewer vectors (mutation tests)

    task run_one(input [127:0] x, input [127:0] exp_y, input integer idx, input [8*8-1:0] tag);
        begin
            @(negedge clk);
            x_in = x; start = 1;
            @(negedge clk); start = 0;
            cyc = 1;
            while (!done) begin @(negedge clk); cyc = cyc + 1; end
            lat = cyc;
            if (lat < lat_min) lat_min = lat;
            if (lat > lat_max) lat_max = lat;
            total = total + 1;
            if (total == 1 || total % 200 == 0)
                $display("  ... %0d vectors done, %0d mismatches, latency %0d clocks", total, errors, lat);
            if (y_out !== exp_y) begin
                errors = errors + 1;
                if (shown < 5) begin
                    shown = shown + 1;
                    $display("MISMATCH %0s #%0d  x=%h\n   got    %h\n   expect %h", tag, idx, x, y_out, exp_y);
                end
            end
        end
    endtask

    initial begin
        $readmemh("test_in.mem", tin);
        $readmemh("test_out.mem", tout);
        $readmemh("stress_in.mem", sin);
        $readmemh("stress_out.mem", sout);
        if ($value$plusargs("n=%d", nv)) begin
            ns = (nv < N_STRESS) ? nv : N_STRESS;
            if (nv > N_VEC) nv = N_VEC;
        end
        repeat (5) @(negedge clk);

        bank = 0; shifts = BUILTIN_SHIFTS;
        for (k = 0; k < nv; k = k + 1) run_one(tin[k], tout[k], k, "synth");
        $display("synthetic model: %0d vectors, %0d mismatches", nv, errors);

        bank = 1; shifts = STRESS_SHIFTS;
        for (k = 0; k < ns; k = k + 1) run_one(sin[k], sout[k], k, "stress");
        $display("stress model   : %0d vectors, total mismatches %0d", ns, errors);

        $display("latency start->done: %0d..%0d clocks (%.2f us at 27 MHz)",
                 lat_min, lat_max, lat_max / 27.0);
        if (errors == 0 && total == nv + ns) $display("RESULT: PASS");
        else $display("RESULT: FAIL (%0d of %0d wrong)", errors, total);
        $finish;
    end

    initial begin #100_000_000; $display("RESULT: FAIL (timeout)"); $finish; end
endmodule
