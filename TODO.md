# Next stage: analysis (not implemented yet)

The current conversion workflow is documented in [README.md](README.md).
Use a separate experimentation branch for future research work and review before
merging.


Next Steps are into two clusters 

## Software Part (Mhd)
1. Better Documentation for the code
2. Write the setup.sh for MAC and WINDOWS and test it 
3. Agree on the in-memory analysis object and implement a Parquet reader that verifies the shared schema/version and session metadata before returning it.
4. Implement public replay from the full history, preserving cancellation and replacement lifecycles alongside current book state.

## Analysis Part (Guillaume and Jules)

1. Experimenting with the new interface and replay to understand the data and the book reconstruction. 
2. Starting to implement the analysis package, including book reconstruction and trade classification.
3. Calculate depth, best bid/ask, spread, and mid-price; then agree on exact LPI/LCI definitions, including how cancellations are classified. 
