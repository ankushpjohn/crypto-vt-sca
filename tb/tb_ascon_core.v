// Self-checking testbench for ascon_core.
//
// Runs 4 key/nonce pairs through the core and compares the state after
// twelve rounds with values from a software model that reproduces all 1089
// official Ascon-AEAD128 known-answer tests. It also checks that `done` is
// high in exactly the right cycle and no other.
//
// The testbench is written in synthesisable Verilog with a single clock
// input, so it can be run two ways:
//   * in a Verilog simulator through tb/sim_ascon_core.v, which supplies the
//     clock and prints the verdict (flow/sim_core.sh);
//   * by formal unrolling in Yosys, e.g.
//       sat -seq 68 -prove-skip 67 -prove finished 1 -prove failed 0
//     which also covers every power-up value of the unreset registers.
module tb_ascon_core (
    input  wire clk,
    output reg  finished,   // all vectors have been run
    output reg  failed      // sticky: some check failed
);
    localparam NVEC   = 4;
    localparam PERIOD = 16;          // cycles allotted to each vector
    localparam LAT    = 13;          // cycles from start to done

    reg  [7:0] t;                    // cycle counter, starts at 0
    wire [7:0] tv    = t - 8'd1;     // time since the first start
    wire [1:0] vec   = tv[5:4];      // vector being run
    wire [3:0] phase = tv[3:0];      // cycle within this vector's slot
    wire       live  = (t != 8'd0) && (tv < NVEC * PERIOD);

    wire rst   = (t == 8'd0);
    wire start = live && (phase == 4'd0);

    reg [63:0] key0, key1, nonce0, nonce1;
    reg [63:0] e0, e1, e2, e3, e4;   // expected state after 12 rounds
    always @* begin
        key0 = 64'd0; key1 = 64'd0; nonce0 = 64'd0; nonce1 = 64'd0;
        e0 = 64'd0; e1 = 64'd0; e2 = 64'd0; e3 = 64'd0; e4 = 64'd0;
        case (vec)
            // official test-vector key 00..0f and nonce 10..1f
            2'd0: begin
                key0 = 64'h0706_0504_0302_0100; key1 = 64'h0f0e_0d0c_0b0a_0908;
                nonce0 = 64'h1716_1514_1312_1110; nonce1 = 64'h1f1e_1d1c_1b1a_1918;
                e0 = 64'hcde3_4900_cdfc_e2c8; e1 = 64'h948c_ba14_1a58_c1cb;
                e2 = 64'h1fec_9b5d_ae69_b43a; e3 = 64'h6205_99fc_d928_dbac;
                e4 = 64'h3d32_90a9_0ed3_b02f;
            end
            // all-zero key and nonce
            2'd1: begin
                key0 = 64'h0000_0000_0000_0000; key1 = 64'h0000_0000_0000_0000;
                nonce0 = 64'h0000_0000_0000_0000; nonce1 = 64'h0000_0000_0000_0000;
                e0 = 64'hfe4f_0978_8ded_5708; e1 = 64'h152c_e52b_6250_d073;
                e2 = 64'h1ba0_258b_92cf_4474; e3 = 64'h9b49_b4a3_2223_8e73;
                e4 = 64'h9f17_67d7_474e_5cff;
            end
            // all-one key and nonce
            2'd2: begin
                key0 = 64'hffff_ffff_ffff_ffff; key1 = 64'hffff_ffff_ffff_ffff;
                nonce0 = 64'hffff_ffff_ffff_ffff; nonce1 = 64'hffff_ffff_ffff_ffff;
                e0 = 64'h7785_4ef1_cef9_4a8a; e1 = 64'h092f_f5f3_b203_7dea;
                e2 = 64'hccbb_5534_08ff_eebb; e3 = 64'ha09a_a043_7c26_2c7e;
                e4 = 64'h2912_d375_e25a_e0b9;
            end
            // random (Python random, seed 20261112)
            2'd3: begin
                key0 = 64'hca23_39e1_35f0_b12d; key1 = 64'h3499_1a7b_815a_2788;
                nonce0 = 64'hd1a8_4e21_61eb_d218; nonce1 = 64'he2d0_9110_bbfa_f9da;
                e0 = 64'he327_84a8_2643_fc82; e1 = 64'h78d7_e510_71cb_d602;
                e2 = 64'h3b51_5030_6439_68d4; e3 = 64'hea93_c42c_2720_a026;
                e4 = 64'h7315_45d5_f874_db71;
            end
        endcase
    end

    wire        busy, done;
    wire [63:0] x0, x1, x2, x3, x4;
    ascon_core dut (
        .clk(clk), .rst(rst), .start(start),
        .key0(key0), .key1(key1), .nonce0(nonce0), .nonce1(nonce1),
        .busy(busy), .done(done),
        .x0(x0), .x1(x1), .x2(x2), .x3(x3), .x4(x4)
    );

    wire expect_done = live && (phase == LAT);
    wire state_ok    = (x0 == e0) && (x1 == e1) && (x2 == e2) && (x3 == e3) && (x4 == e4);
    wire bad         = !rst && ((done != expect_done) || (done && !state_ok));

    initial begin
        t        = 8'd0;
        finished = 1'b0;
        failed   = 1'b0;
    end

    always @(posedge clk) begin
        if (t != 8'hff)
            t <= t + 8'd1;
        if (bad)
            failed <= 1'b1;
        if (t == NVEC * PERIOD + 8'd1)
            finished <= 1'b1;
    end
endmodule
