// Self-checking testbench for ascon_core, driven by a vector file.
//
// The file comes from model/gen_core_vectors.py, which takes every expected
// value from the reference model model/ascon_ref.py. Its format is described
// there. For each vector the testbench applies key and nonce with `start`
// and then checks, in every cycle:
//   * x0..x4 against the model: the loaded state, then the state after each
//     of the twelve rounds (not only the final one);
//   * `busy`, high for the twelve cycles after `start`;
//   * `done`, high in the thirteenth cycle after `start` and in no other.
// Some vectors are cut short by an early `start` or by `rst`; such a run must
// not produce `done`, and the run that follows must be correct.
//
// The same testbench checks the RTL (flow/sim_core.sh) and the gate-level
// netlist (flow/synth_core.sh). Simulation only; nothing here is synthesised.
//
//   vvp build/tb_ascon_core.vvp +vectors=build/core_vectors.hex   (+vcd for waveforms)
`timescale 1ns / 1ps
module tb_ascon_core;
    localparam LAT        = 13;      // cycles from start to done
    localparam MAX_ERRORS = 10;

    reg         clk = 1'b0;
    reg         rst, start;
    reg  [63:0] key0, key1, nonce0, nonce1;
    wire        busy, done;
    wire [63:0] x0, x1, x2, x3, x4;

    ascon_core dut (
        .clk(clk), .rst(rst), .start(start),
        .key0(key0), .key1(key1), .nonce0(nonce0), .nonce1(nonce1),
        .busy(busy), .done(done),
        .x0(x0), .x1(x1), .x2(x2), .x3(x3), .x4(x4)
    );

    always #5 clk = ~clk;

    // ---- one line of the vector file -------------------------------------
    reg [1023:0]        path;
    integer             fd, got;
    reg [7:0]           f_wait, f_rst;
    reg [63:0]          f_key0, f_key1, f_nonce0, f_nonce1;
    reg [LAT*320-1:0]   f_states;    // 13 states, the loaded one in the top bits

    // ---- expectation tracker ---------------------------------------------
    // age = cycles since the start of the run in progress (1..13), 0 if none.
    // It follows the same inputs as the core, at the same clock edge.
    integer             age = 0;
    integer             cur = -1;    // vector the run in progress belongs to
    reg [LAT*320-1:0]   exp_states;
    integer             n_vec = 0, n_done = 0, n_cut = 0, errors = 0;
    reg                 armed = 1'b0;

    always @(posedge clk) begin
        if (rst) begin
            if (age != 0 && age != LAT) n_cut = n_cut + 1;
            age <= 0;
        end else if (start) begin
            if (age != 0 && age != LAT) n_cut = n_cut + 1;
            age        <= 1;
            cur        <= n_vec - 1;
            exp_states <= f_states;
        end else if (age == LAT)
            age <= 0;
        else if (age != 0)
            age <= age + 1;
    end

    wire [319:0] exp_state = exp_states[(LAT - age) * 320 +: 320];
    wire         exp_busy  = (age >= 1) && (age <= LAT - 1);
    wire         exp_done  = (age == LAT);

    // Outputs are compared in the middle of the cycle, when they are settled
    // in both RTL and gate-level simulation.
    always @(negedge clk) if (armed) begin
        if (age != 0 && {x0, x1, x2, x3, x4} !== exp_state) begin
            errors = errors + 1;
            $display("MISMATCH  vector %0d, state after %0d round(s)", cur, age - 1);
            $display("  expected %h", exp_state);
            $display("  got      %h", {x0, x1, x2, x3, x4});
        end
        if (done !== exp_done) begin
            errors = errors + 1;
            $display("MISMATCH  vector %0d, cycle %0d after start: done = %b, expected %b",
                     cur, age, done, exp_done);
        end
        if (busy !== exp_busy) begin
            errors = errors + 1;
            $display("MISMATCH  vector %0d, cycle %0d after start: busy = %b, expected %b",
                     cur, age, busy, exp_busy);
        end
        if (done === 1'b1 && exp_done) n_done = n_done + 1;
        if (errors >= MAX_ERRORS) begin
            $display("RESULT: FAILED (stopped after %0d errors)", errors);
            $finish;
        end
    end

    // ---- stimulus --------------------------------------------------------
    // Inputs change on the falling edge. Key and nonce carry random values
    // whenever `start` is low, to show that the core samples them only then.
    task idle_inputs;
        begin
            start  = 1'b0;
            key0   = {$random, $random};
            key1   = {$random, $random};
            nonce0 = {$random, $random};
            nonce1 = {$random, $random};
        end
    endtask

    initial begin
        if ($test$plusargs("vcd")) begin
            $dumpfile("build/tb_ascon_core.vcd");
            $dumpvars(0, tb_ascon_core);
        end
        if (!$value$plusargs("vectors=%s", path))
            path = "build/core_vectors.hex";
        fd = $fopen(path, "r");
        if (fd == 0) begin
            $display("RESULT: FAILED (cannot open vector file %0s)", path);
            $finish;
        end

        rst = 1'b1;
        idle_inputs;
        @(negedge clk);
        @(negedge clk);
        rst    = 1'b0;
        armed <= 1'b1;

        got = $fscanf(fd, "%h %h %h %h %h %h %h",
                      f_wait, f_rst, f_key0, f_key1, f_nonce0, f_nonce1, f_states);
        while (got == 7) begin
            n_vec  = n_vec + 1;
            start  = 1'b1;
            key0   = f_key0;
            key1   = f_key1;
            nonce0 = f_nonce0;
            nonce1 = f_nonce1;
            @(negedge clk);
            idle_inputs;
            repeat (f_wait) @(negedge clk);
            if (f_rst[0]) begin
                rst = 1'b1;
                @(negedge clk);
                rst = 1'b0;
            end
            got = $fscanf(fd, "%h %h %h %h %h %h %h",
                          f_wait, f_rst, f_key0, f_key1, f_nonce0, f_nonce1, f_states);
        end
        // A clean end of file reads no field at all; anything else is a bad line.
        if (got > 0 || !$feof(fd)) begin
            errors = errors + 1;
            $display("vector file %0s: malformed line after vector %0d", path, n_vec - 1);
        end
        repeat (LAT + 2) @(negedge clk);

        $display("%0d vectors: %0d ran to completion, %0d cut short, %0d errors",
                 n_vec, n_done, n_cut, errors);
        if (n_vec == 0 || n_done + n_cut != n_vec) begin
            errors = errors + 1;
            $display("vector count does not add up");
        end
        if (errors == 0) $display("RESULT: all checks passed");
        else             $display("RESULT: FAILED");
        $finish;
    end
endmodule
