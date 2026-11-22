// =============================================================================
// tb_top : the complete board design (UART + parser + loader + engine) driven
// over its real UART pins, the way the PC does it. UART runs at 8 clocks per
// bit and the timeout is shortened so the simulation finishes in minutes; the
// logic is otherwise exactly what goes on the board.
//
//   1. C5 info               -> built-in model, CRC-32 of the synthetic model
//   2. 30 inferences         -> bit-exact vs Python, argmax, latency
//   3. damaged upload        -> status 1 (CRC error), old model still answers right
//   4. interrupted upload    -> status 2 (timeout), old model still answers right
//   5. upload with shift 24  -> status 3, old model still answers right
//   6. stray byte + half frame + timeout -> next frame still works
//   7. good stress upload    -> status 0, CRC, loads = 1, C5 says uploaded; 30 stress vectors
//   8. good synthetic upload -> status 0, loads = 2 (back in bank 0); 30 synthetic vectors
// =============================================================================
`timescale 1ns/1ps
module tb_top;
    `include "num_vectors.vh"
    `include "ns64_builtin.vh"
    `include "tb_load.vh"
    localparam BIT = 8;                      // clocks per UART bit (board: 234)
    localparam TMO = 3000;                   // frame timeout in clocks (board: 270000)

    reg clk = 0;  always #18.5185 clk = ~clk;
    reg rx = 1;
    wire tx;
    wire [5:0] leds;
    tangnano20k_ns64 #(.CLKS_PER_BIT(BIT), .TIMEOUT(TMO)) dut (
        .clk(clk), .uart_rx(rx), .uart_tx(tx), .leds(leds));

    reg [127:0] tin  [0:N_VEC-1];
    reg [127:0] tout [0:N_VEC-1];
    reg [3:0]   tam  [0:N_VEC-1];
    reg [127:0] sin  [0:N_STRESS-1];
    reg [127:0] sout [0:N_STRESS-1];
    reg [3:0]   sam  [0:N_STRESS-1];
    reg [7:0]   up_syn [0:UP_BYTES-1];
    reg [7:0]   up_st  [0:UP_BYTES-1];
    reg [7:0]   up_bad [0:UP_BYTES-1];
    reg [7:0]   up_bs  [0:UP_BYTES-1];

    integer errors = 0, checks = 0, lat_seen = -1, i, k;
    reg pat_ok;
    realtime t_req, t_rep;
    reg [7:0] r [0:63];

    task fail(input [8*60-1:0] msg); begin errors = errors + 1; $display("  FAIL: %0s", msg); end endtask
    // a broken design does not need the full run: stop after 5 errors
    always @(errors) if (errors >= 5) begin $display("RESULT: FAIL (stopped after %0d errors)", errors); $finish; end
    task check(input ok, input [8*60-1:0] msg); begin checks = checks + 1; if (!ok) fail(msg); end endtask

    task send_byte(input [7:0] b);
        integer n;
        begin
            rx = 0; repeat (BIT) @(posedge clk);
            for (n = 0; n < 8; n = n + 1) begin rx = b[n]; repeat (BIT) @(posedge clk); end
            rx = 1; repeat (BIT) @(posedge clk);
        end
    endtask

    task recv_byte(output [7:0] b);
        integer n;
        begin
            @(negedge tx);
            repeat (BIT/2) @(posedge clk);
            for (n = 0; n < 8; n = n + 1) begin repeat (BIT) @(posedge clk); b[n] = tx; end
            repeat (BIT) @(posedge clk);
        end
    endtask

    task recv_n(input integer n);
        integer m; begin for (m = 0; m < n; m = m + 1) recv_byte(r[m]); end
    endtask

    // ---- one inference: frame out, 20-byte reply in, compare everything
    task infer(input [127:0] x, input [127:0] y, input [3:0] am, input integer idx);
        integer lat;
        reg [127:0] got;
        begin
            fork
                begin send_byte(8'hA5); for (i = 0; i < 16; i = i + 1) send_byte(x[i*8 +: 8]); end
                recv_n(20);
            join
            for (i = 0; i < 16; i = i + 1) got[i*8 +: 8] = r[1 + i];
            lat = {r[19], r[18]};
            checks = checks + 1;
            if (r[0] !== 8'h5A || got !== y || r[17] !== {4'd0, am}) begin
                errors = errors + 1;
                if (errors < 8)
                    $display("  FAIL vector %0d: hdr %h argmax %0d (exp %0d)\n     got %h\n     exp %h",
                             idx, r[0], r[17], am, got, y);
            end
            if (lat_seen < 0) lat_seen = lat;
            else if (lat != lat_seen) fail("latency changed");
        end
    endtask

    task run_vectors(input sel, input integer n, input integer first);
        begin
            for (k = first; k < first + n; k = k + 1)
                if (sel == 0) infer(tin[k], tout[k], tam[k], k);
                else          infer(sin[k], sout[k], sam[k], k);
        end
    endtask

    // ---- upload (all or part of a frame); which: 0 synth, 1 stress, 2 bad CRC, 3 bad shift
    task upload(input integer which, input integer nbytes);
        integer m;
        reg [7:0] b;
        begin
            send_byte(8'hC3);
            for (m = 0; m < nbytes; m = m + 1) begin
                case (which)
                    0: b = up_syn[m]; 1: b = up_st[m]; 2: b = up_bad[m]; default: b = up_bs[m];
                endcase
                send_byte(b);
            end
        end
    endtask

    task load_reply(input [7:0] exp_status, input [31:0] exp_crc, input [7:0] exp_loads, input check_crc);
        reg [31:0] c;
        begin
            recv_n(7);
            c = {r[5], r[4], r[3], r[2]};
            $display("  reply: 3C status=%0d crc=%08h loads=%0d", r[1], c, r[6]);
            check(r[0] === 8'h3C, "load reply header");
            check(r[1] === exp_status, "load status");
            check(r[6] === exp_loads, "loads counter");
            if (check_crc) check(c === exp_crc, "reported CRC-32");
        end
    endtask

    task info(input [31:0] exp_crc, input [7:0] exp_src, input [7:0] exp_loads);
        reg [31:0] c;
        begin
            fork send_byte(8'hC5); recv_n(7); join
            c = {r[4], r[3], r[2], r[1]};
            $display("  info : 5C crc=%08h source=%0d loads=%0d", c, r[5], r[6]);
            check(r[0] === 8'h5C && c === exp_crc && r[5] === exp_src && r[6] === exp_loads, "info reply");
        end
    endtask

    initial begin
        $readmemh("test_in.mem", tin);   $readmemh("test_out.mem", tout);   $readmemh("test_amax.mem", tam);
        $readmemh("stress_in.mem", sin); $readmemh("stress_out.mem", sout); $readmemh("stress_amax.mem", sam);
        $readmemh("up_synth.mem", up_syn);  $readmemh("up_stress.mem", up_st);
        $readmemh("up_badcrc.mem", up_bad); $readmemh("up_badshift.mem", up_bs);
        repeat (20) @(posedge clk);

        $display("1. info (built-in)");
        info(BUILTIN_CRC32, 0, 0);
        $display("2. 30 synthetic inferences");
        run_vectors(0, 30, 0);
        $display("   latency reported by the chip: %0d clocks", lat_seen);

        $display("3. damaged upload (one bit flipped)");
        fork upload(2, UP_BYTES); load_reply(1, CRC_BAD_RX, 0, 1); join
        run_vectors(0, 10, 30);
        info(BUILTIN_CRC32, 0, 0);

        $display("4. interrupted upload (5000 of %0d bytes, then silence)", UP_BYTES);
        fork upload(1, 5000); load_reply(2, 0, 0, 0); join
        run_vectors(0, 10, 40);

        $display("5. upload with a shift of 24 (correct CRC)");
        fork upload(3, UP_BYTES); load_reply(3, CRC_BADSHIFT, 0, 1); join
        run_vectors(0, 10, 50);
        info(BUILTIN_CRC32, 0, 0);

        $display("6. stray byte + half frame, then timeout");
        send_byte(8'h00);
        send_byte(8'hA5); send_byte(8'h11); send_byte(8'h22);
        repeat (TMO + 100) @(posedge clk);
        run_vectors(0, 5, 60);
        check(leds[5] === 1'b0, "LED5 (error seen) on");

        $display("7. good upload: stress model");
        fork upload(1, UP_BYTES); load_reply(0, CRC_STRESS, 1, 1); join
        info(CRC_STRESS, 1, 1);
        check(leds[3] === 1'b0 && leds[4] === 1'b0, "LED3 (bank 1) and LED4 (uploaded) on");
        run_vectors(1, 30, 0);

        $display("8. good upload: synthetic model again (goes into bank 0)");
        fork upload(0, UP_BYTES); load_reply(0, CRC_SYNTH, 2, 1); join
        info(CRC_SYNTH, 1, 2);
        check(leds[3] === 1'b1, "LED3 off (bank 0)");
        run_vectors(0, 30, 65);

        $display("9. link diagnosis commands");
        fork begin send_byte(8'hD1); send_byte(8'h00); send_byte(8'h00); end recv_n(3); join
        check(r[0] === 8'h1D && r[1] === 8'h00 && r[2] === 8'h00, "D1 0 0 reply");
        fork begin send_byte(8'hD2); send_byte(8'd20); send_byte(8'd2); end recv_n(21); join
        pat_ok = (r[0] === 8'h2D);
        for (i = 0; i < 20; i = i + 1) if (r[1 + i] !== i) pat_ok = 0;
        if (!pat_ok) begin
            $write("  D2 20 2 got:"); for (i = 0; i < 21; i = i + 1) $write(" %h", r[i]); $write("\n");
        end
        check(pat_ok, "D2 20 2 (counting pattern)");
        fork begin send_byte(8'hD2); send_byte(8'd5); send_byte(8'd3); end recv_n(6); join
        check(r[0] === 8'h2D && r[1] === 8'h55 && r[5] === 8'h55, "D2 5 3 (0x55 pattern)");
        // 2 stop bits + wait 4*256 = 1024 clocks before each reply
        fork begin send_byte(8'hD1); send_byte(8'h01); send_byte(8'h04); end recv_n(3); join
        check(r[0] === 8'h1D && r[1] === 8'h01 && r[2] === 8'h04, "D1 1 4 reply");
        send_byte(8'hC5);
        t_req = $time;
        recv_n(7);
        t_rep = $time;
        $display("  C5 with wait 1024 clocks: reply took %0d clocks after the request", (t_rep - t_req) / 37.037);
        check((t_rep - t_req) / 37.037 > 1024 + 7 * 11 * BIT, "reply delayed by >= 1024 clocks with 2 stop bits");
        check(r[0] === 8'h5C, "info reply after D1 1 4");
        run_vectors(0, 5, 95);
        fork begin send_byte(8'hD1); send_byte(8'h00); send_byte(8'h00); end recv_n(3); join
        run_vectors(0, 5, 100);

        $display("checks %0d (inference frames included), errors %0d", checks, errors);
        if (errors == 0) $display("RESULT: PASS"); else $display("RESULT: FAIL");
        $finish;
    end
endmodule
