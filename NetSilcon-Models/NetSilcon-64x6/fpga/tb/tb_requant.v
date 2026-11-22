// =============================================================================
// tb_requant : the shared requantizer against a reference written in plain
// integer arithmetic, for EVERY shift 0..23, ReLU on and off, and the corner
// sums (0, +-1, the 24-bit limits, +-1,073,152 = worst case of the network) plus
// 20,000 random sums. One value enters per clock, the result appears 2 clocks later.
// =============================================================================
`timescale 1ns/1ps
module tb_requant;
    reg clk = 0;
    always #5 clk = ~clk;

    reg  signed [23:0] acc = 0;
    reg         [4:0]  s = 0;
    reg                relu = 0;
    wire        [7:0]  y;
    ns64_requant dut (.clk(clk), .acc_in(acc), .s(s), .relu(relu), .y(y));

    function [7:0] ref_q(input integer a_in, input integer sh, input integer r);
        integer a, v;
        begin
            a = (r && a_in < 0) ? 0 : a_in;
            v = (a + (sh ? (1 << (sh - 1)) : 0)) >>> sh;
            if (r) ref_q = (v > 127) ? 127 : v;
            else   ref_q = (v > 127) ? 127 : (v < -128) ? -128 : v;
        end
    endfunction

    integer corner [0:13];
    reg [7:0] exp_pipe [0:2];
    reg       v_pipe   [0:2];
    integer errors = 0, n = 0, i, sh, r, seed = 64;

    task push(input integer a, input integer sh_, input integer r_);
        begin
            @(negedge clk);
            acc = a; s = sh_; relu = r_;          // acc is 24 bits: the reference uses the same value
            exp_pipe[0] = ref_q(acc, sh_, r_); v_pipe[0] = 1;
        end
    endtask

    // compare 2 clocks later
    always @(posedge clk) begin
        #1;
        exp_pipe[2] = exp_pipe[1]; v_pipe[2] = v_pipe[1];
        exp_pipe[1] = exp_pipe[0]; v_pipe[1] = v_pipe[0];
        v_pipe[0] = 0;
        if (v_pipe[2]) begin                 // pushed 2 clocks ago -> y must hold its result now
            n = n + 1;
            if (y !== exp_pipe[2]) begin
                errors = errors + 1;
                if (errors < 6) $display("MISMATCH got %0d expect %0d", $signed(y), $signed(exp_pipe[2]));
            end
        end
    end

    initial begin
        v_pipe[0] = 0; v_pipe[1] = 0; v_pipe[2] = 0;
        corner[0] = 0;        corner[1] = 1;        corner[2] = -1;
        corner[3] = 127;      corner[4] = 128;      corner[5] = -128;   corner[6] = -129;
        corner[7] = 8388607;  corner[8] = -8388608; corner[9] = 1073152; corner[10] = -1073152;
        corner[11] = 65535;   corner[12] = -65536;  corner[13] = 32767;
        for (sh = 0; sh <= 23; sh = sh + 1)
            for (r = 0; r <= 1; r = r + 1) begin
                for (i = 0; i < 14; i = i + 1) push(corner[i], sh, r);
                for (i = 0; i < 400; i = i + 1) push($random(seed) % 8388608, sh, r);
                // values just around each rounding boundary of this shift
                for (i = -3; i <= 3; i = i + 1) begin
                    push((1 << sh) / 2 + i, sh, r);
                    push(-((1 << sh) / 2) + i, sh, r);
                    push(127 * (1 << sh) + i, sh, r);
                    push(-128 * (1 << sh) + i, sh, r);
                end
            end
        repeat (4) @(negedge clk);
        $display("requantizer: %0d values (shifts 0..23, ReLU on/off), %0d mismatches", n, errors);
        if (errors == 0 && n > 20000) $display("RESULT: PASS"); else $display("RESULT: FAIL");
        $finish;
    end
endmodule
