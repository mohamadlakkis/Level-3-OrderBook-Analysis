THe intial step is to run ubuntu_setup.sh to download the raw data  (.gz)

Next we need to convert this .gz into parquet file, it will convert the .gz into .parquet with default values and out paths and ticker is apple. WE can play around with this I made a clie arugments you can check book [book-reconstruction/README.md](book-reconstruction/README.md)

For more details the output for now will be in data/processed/AAPL_2019-12-30.parquet (if default values used). You can also check a detailed report in data/processed (it is a .json) file it contains useful descriptiove information on what we did just convert (how many values, and some other statistcics) NOT: THis conversation included tests and checks, if something fails it will give you a report and return 1 instead of failing silently, it will also give you a diagnostic report which it will print its path. (These checks establish structural and selected-ticker replay consistency.)
(it will seem complex but it is not under the hood it is doing very simple things) check the [book-reconstruction/README.md](book-reconstruction/README.md) for a lot more details on this, it is really interesting. 

The next couple of lines explains the high level flow of the code and why I made it this way. 

We have a messy binary file (.gz) which we need to convert into a more structured format (parquet). And then the analysis part we need to read this parquet file and do some analysis on it. But we need to ask ourselves how will we convert into this parquet file, I mean what data will we store and how (i.e. what schema will we use), because this also affect tha analysis part, because it is going to read this parquet file. And the good sofwate design is to make a common schema which is going to be used by both the conversion and analysis part. 

```
book_reconstruction ->  common <- analysis 
```

Don't worry about the details of the code I will explain everything in much better documentation, but this is essentialy the high level. The common [common/SCHEMA.md](common/SCHEMA.md) shows us the schema this way you can directly start the analysis part without worrying about the conversion part. 

So direct next Steps: 

Run 

(one small thing I am using uv much faster than pip), you could simply download it using pip install uv. and then uv will be installed (or check this https://docs.astral.sh/uv/getting-started/installation/)

```
bash ubuntu_setup.sh (Ask an LLM to give you the version for your operating system)
uv sync --locked (this will install all the dependencies in a virtual environment analogue to pip install -r requirements.txt)
uv run itch-convert (this will convert the .gz into .parquet and also give you a report in data/processed)
```


Before Merging with main always run 

```
uv run pytest
```