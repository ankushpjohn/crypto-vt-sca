// Toy design for the first end-to-end checkpoint: one Ascon S-box column
// between two registers.
//
//   d -> [s_in register] -> S-box -> [s_out register] -> q
//
// s_in stands in for the Ascon state register, and the S-box for the round
// logic that has settled when the clock is stopped. The register-to-register
// path gives OpenSTA something to time.
//
// d[4] is x0 (the S-box input's most significant bit) and d[0] is x4, so d
// read as an integer indexes the standard's S-box table directly. q uses the
// same order for the output.
module sbox_col_toy (
    input  wire       clk,
    input  wire [4:0] d,
    output wire [4:0] q
);
    reg  [4:0] s_in;
    reg  [4:0] s_out;
    wire [4:0] y;

    ascon_sbox #(.W(1)) u_sbox (
        .x0(s_in[4]), .x1(s_in[3]), .x2(s_in[2]), .x3(s_in[1]), .x4(s_in[0]),
        .y0(y[4]),    .y1(y[3]),    .y2(y[2]),    .y3(y[1]),    .y4(y[0])
    );

    always @(posedge clk) begin
        s_in  <= d;
        s_out <= y;
    end

    assign q = s_out;
endmodule
