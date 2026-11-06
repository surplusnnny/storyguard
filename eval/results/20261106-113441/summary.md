# 평가 결과 20261106-113441

원본: `eval\results\20261106-113441/results.csv` (10행), 집계: `eval\results\20261106-113441/summary.csv`

| 모델 | 재시도 | 1차 통과율 | 최종 성공률(의도 유지) | 위험 요청 1차 파손율 | 요청하지 않은 변경 비율 | 평균 LLM 시간 |
| --- | --- | --- | --- | --- | --- | --- |
| gpt-5.4-mini | on | 0% | 30% | 90% | 20% | 27642.2ms |

계산 방법 (results.csv의 열)
- 1차 통과율 = first_pass 평균 (LLM이 처음 고친 게임이 엔딩 도달 가능하고 요청하지 않은 변경이 없음)
- 최종 성공률 = success 평균 (최종 통과 AND 요청한 변경이 최종 게임에 남아 있음, checks로 확인)
- 위험 요청 1차 파손율 = category=risky이고 modified=1인 행의 (1 - first_reachable) 평균 (수정을 거부·질문한 요청은 뺌)
- 수정 시도율(summary.csv의 modified_rate) = modified 평균
- 요청하지 않은 변경 비율 = first_unintended 평균
- 평균 LLM 시간 = llm_ms 평균 (요청 1건의 모든 LLM 호출 합)