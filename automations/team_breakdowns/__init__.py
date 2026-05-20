"""Team Breakdowns ('Next Promotion') section — fills the per-rep tracking
section that Raf maintains under the metrics section on certain tabs.

Auto-detects: column-A 'Next Promotion' header + matching 'Total Units'
row below. Tab can have multiple sections (Jay Turnage has 2). For each rep
listed in column B, looks up their week's production from the OPT phase's
PRODUCT SALES SUMMARY crosstab and writes 'X NI, Y DTV, Z NL, W UG'.
Total Units row sums across listed reps."""
