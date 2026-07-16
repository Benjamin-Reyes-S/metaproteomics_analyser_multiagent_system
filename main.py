from typing import TypedDict, Any
from langgraph.graph import StateGraph, START, END
from agents import statistical_analyser, study_planer, study_validator, outcome_auditor



def study_planner_node(state) -> TypeDict:
    result= study_planer.invoke(
        message
    )


# orchestration state decides which node runs nex

builder = StateGraph(MetaproteomicsAnylisisState)

# architecture of the graph 
builder.add_node("study design", study_planner_node)
builder.add_node("analyze and plot", statistical_analyser)
builder.add_node("studdy validator", study_validator)
builder.add_node("evaluate output", outcome_auditor)

builder.add_edge(START, "Study design")
builder.add_edge("study design", "evaluate output")
builder.add_edge("evaluate output", "analyze and plot")
builder.add_edge("analyze and plot", "studdy validator")
builder.add_edge("studdy validator", END)

graph = builder.compile()

result = graph.invoke({

})

print(result)