// tb_netsilcon_6x4_lgn_exp01_w720.v -- compares the Verilog against Python golden vectors (bit-exact)
`timescale 1ns/1ps
module tb;
    reg  [7:0] fl, fr, rl, rr;
    wire [1:0] speed;  wire [2:0] steer;
    reg  [39:0] mem [0:4095];
    integer i, err;
    netsilcon_6x4_lgn_exp01_w720 dut(.fl(fl), .fr(fr), .rl(rl), .rr(rr), .speed(speed), .steer(steer));
    initial begin
        $readmemh("golden.hex", mem);
        err = 0;
        for (i = 0; i < 4096; i = i + 1) begin
            {fl, fr, rl, rr} = mem[i][39:8];
            #10;
            if (speed !== mem[i][5:4] || steer !== mem[i][2:0]) begin
                err = err + 1;
                if (err < 10) $display("MISMATCH %0d in=%h got sp=%0d st=%0d exp sp=%0d st=%0d",
                                       i, mem[i][39:8], speed, steer, mem[i][5:4], mem[i][2:0]);
            end
        end
        $display("RESULT vectors=%0d mismatches=%0d %s", 4096, err, (err==0) ? "PASS" : "FAIL");
        $finish;
    end
endmodule
