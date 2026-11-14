# `cuda-4gb`

`embed` is bge-m3 and `rerank` bge-reranker-v2-m3, both multilingual, both at Q8, on the ports
18081 and 18082. Measured on a GTX 1650: 1.6 GB of card memory for both; a query embedded in about
40 ms, about 34 short statements embedded and 32 pairs reranked a second, the card at 98–99 %
while it works. The card's memory would hold larger models; its speed is what the choice is bound
by, since both run for every message. One CPU core runs at 100 % per working server — the CUDA
driver's thread waiting on the card, not the model computed on the CPU. A container's first
request after its start takes tens of seconds, which is why `up` ends with a real answer.
