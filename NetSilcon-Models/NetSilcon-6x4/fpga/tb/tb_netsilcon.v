// =============================================================================
// Testbench: streams every golden vector into NetSilcon-6x4 (one per clock),
// compares every output against the Python integer model, bit for bit.
// Then tests the model-update port: rewrites one bias and checks the effect.
// =============================================================================
`timescale 1ns/1ps
module tb_netsilcon;
    parameter PHASES = 2;
    `include "num_vectors.vh"

    reg         clk = 0;
    reg         in_valid = 0;
    reg  [31:0] x_in = 0;
    wire        out_valid;
    wire [15:0] y_out;
    wire        fault;
    reg         param_we = 0;
    reg  [7:0]  param_addr = 0;
    reg  [15:0] param_data = 0;

    netsilcon_top #(.PHASES(PHASES)) dut (
        .clk(clk), .in_valid(in_valid), .x_in(x_in),
        .out_valid(out_valid), .y_out(y_out), .fault(fault),
        .param_we(param_we), .param_addr(param_addr), .param_data(param_data));

    always #5 clk = ~clk;          // 100 MHz

    reg [31:0] vin  [0:NUM_VECTORS-1];
    reg [15:0] vout [0:NUM_VECTORS-1];
    integer sent = 0, got = 0, errors = 0, faults = 0;
    integer first_in_cycle = -1, first_out_cycle = -1, cycle = 0;

    always @(posedge clk) cycle <= cycle + 1;

    // ---- checker
    always @(posedge clk) begin
        if (out_valid && got < NUM_VECTORS) begin
            if (first_out_cycle < 0) first_out_cycle = cycle;
            if (y_out !== vout[got]) begin
                errors = errors + 1;
                if (errors <= 10)
                    $display("MISMATCH vector %0d: x=%h  got y=%h  expected %h", got, vin[got], y_out, vout[got]);
            end
            if (fault) faults = faults + 1;
            got = got + 1;
        end
    end

    integer n;
    reg [15:0] before;
    initial begin
        $readmemh("test_in.mem",  vin);
        $readmemh("test_out.mem", vout);
        $display("NetSilcon-6x4 testbench: %0d golden vectors", NUM_VECTORS);

        repeat (3) @(posedge clk);
        // stream at full rate: one vector every PHASES clocks
        for (n = 0; n < NUM_VECTORS; n = n + 1) begin
            @(negedge clk);
            in_valid = 1; x_in = vin[n];
            if (n == 0) first_in_cycle = cycle;
            if (PHASES == 2) begin @(negedge clk) in_valid = 0; end
        end
        @(negedge clk) in_valid = 0;
        repeat (12*PHASES) @(posedge clk);

        $display("------------------------------------------------------------");
        $display("Vectors checked   : %0d", got);
        $display("Mismatches        : %0d", errors);
        $display("Latency           : %0d clocks", first_out_cycle - first_in_cycle);
        $display("Throughput        : 1 inference every %0d clock(s)", PHASES);
        $display("Fault decisions   : %0d of %0d", faults, got);

        // ---- model-update test: change bias of output neuron y1 (address 144+25) and re-run vector 0
        @(negedge clk);
        in_valid = 1; x_in = vin[0];
        @(negedge clk) in_valid = 0;
        repeat (10*PHASES) @(posedge clk);
        before = y_out;
        @(negedge clk);
        param_we = 1; param_addr = 8'd169; param_data = 16'h7FFF;   // huge fault bias
        @(negedge clk) param_we = 0;
        in_valid = 1; x_in = vin[0];
        @(negedge clk) in_valid = 0;
        repeat (10*PHASES) @(posedge clk);
        $display("Update port test  : y before %h, after bias write %h -> %s",
                 before, y_out, (y_out[15:8] == 8'h7f) ? "OK" : "FAILED");

        if (errors == 0 && got == NUM_VECTORS && y_out[15:8] == 8'h7f)
            $display("RESULT: PASS - hardware matches the Python int8 model bit for bit");
        else
            $display("RESULT: FAIL");
        $finish;
    end
endmodule
