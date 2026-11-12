// Ascon 5-bit S-box in bitsliced Boolean form (NIST SP 800-232, substitution
// layer). Written as gates rather than a lookup table so that synthesis keeps
// the structure a real Ascon core has.
//
// W is the number of S-box columns evaluated in parallel: W = 1 for the toy
// single column, W = 64 for the full permutation, where x0..x4 are the five
// state words. Bit j of every word belongs to column j.
//
// Within one column, x0 is the most significant bit of the 5-bit S-box input
// and x4 the least significant, as in the standard's lookup table.
module ascon_sbox #(
    parameter W = 1
) (
    input  wire [W-1:0] x0,
    input  wire [W-1:0] x1,
    input  wire [W-1:0] x2,
    input  wire [W-1:0] x3,
    input  wire [W-1:0] x4,
    output wire [W-1:0] y0,
    output wire [W-1:0] y1,
    output wire [W-1:0] y2,
    output wire [W-1:0] y3,
    output wire [W-1:0] y4
);
    // Input linear part.
    wire [W-1:0] a0 = x0 ^ x4;
    wire [W-1:0] a1 = x1;
    wire [W-1:0] a2 = x2 ^ x1;
    wire [W-1:0] a3 = x3;
    wire [W-1:0] a4 = x4 ^ x3;

    // Non-linear part (the chi-like layer): b_i = a_i ^ (~a_{i+1} & a_{i+2}).
    wire [W-1:0] b0 = a0 ^ (~a1 & a2);
    wire [W-1:0] b1 = a1 ^ (~a2 & a3);
    wire [W-1:0] b2 = a2 ^ (~a3 & a4);
    wire [W-1:0] b3 = a3 ^ (~a4 & a0);
    wire [W-1:0] b4 = a4 ^ (~a0 & a1);

    // Output linear part.
    assign y0 = b0 ^ b4;
    assign y1 = b1 ^ b0;
    assign y2 = ~b2;
    assign y3 = b3 ^ b2;
    assign y4 = b4;
endmodule
