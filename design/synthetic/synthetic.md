# Synthetic AI harness core

Synthetic (`synthetic.py`) is the AI harness core of AI Assassin: the prompt library, the seed
context, the AI connections and the tool call protocol. It answers every exchange from the DAG rather than from a
transcript: a replica anchored at an item is answered above the item's seed context, and the reply
either continues the dialog or condenses it back into the DAG through tree calls.
