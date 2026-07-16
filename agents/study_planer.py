from langchain.agents import create_agent

prompt= ' you are a study planer for metaproteomics data analysis\
        your tasks are:\
        -Inspect the data\
        -Recognize which type of properties : (e.g. different batches vs one batch, samples size)\
        -plan a downstream analysis for this data taking in consideration the properties you recognized

'

planer_agent = create_agent(model="google_genai:gemini-3.5-flash", tools=tools, system_prompt= prompt)
