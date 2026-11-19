# EnergyPlus 단일 실 온도 응답 비교

가상 단일 실에서 발열을 끈 뒤 MA-BEMS의 실별 외기 열교환 항과 EnergyPlus 26.2.0의 공기 온도를 비교했습니다. 캠퍼스의 연간 에너지 사용량과 피크를 검증하려면 HVAC·벽체·일사·재실 조건을 포함한 별도 모델과 실측 자료가 필요합니다.

- EnergyPlus에서 외기 25°C, 단열된 1,061.88 m³ 공간에 외기를 0.06321 m³/s로 공급했습니다. 08:00~12:00에 대류 발열 750 W를 넣고, 그 후 12시간 동안 끈 상태를 관찰했습니다.
- 두 모델은 정오 실온 30.735°C에서 시작하고 명목 열손실 시정수 280분을 공유했습니다. MA-BEMS는 1분마다 `(25 − 실온) / 280`을 실온에 더했습니다. EnergyPlus는 구역 공기 열수지를 풉니다.
- 720개 분 단위 온도를 비교한 RMSE는 **0.058°C**, 최대 절대 오차는 **0.082°C**입니다. [전체 요약](summary.json)

[EnergyPlus 26.2.0](https://github.com/NatLabRockies/EnergyPlus/releases/tag/v26.2.0)과 Python 3으로 저장소 루트에서 실행합니다.

```sh
python3 eval/followup/energyplus/check.py --energyplus /path/to/energyplus
```

원본 IDF의 출처는 [EnergyPlus 단일 실 예제](https://github.com/NatLabRockies/EnergyPlus/blob/v26.2.0/testfiles/1ZoneUncontrolled.idf)이며, [라이선스](LICENSE-EnergyPlus.txt)를 함께 제공합니다. 스크립트는 `energyplus/runs/`에 EnergyPlus 출력, 분 단위 양쪽 온도와 오차(`cooldown.csv`), 요약(`summary.json`)을 기록합니다. 벽체를 무질량으로 설정한 이 테스트에서는 열용량 관련 EnergyPlus 경고 1건이 발생합니다. 해당 실행은 심각 오류 없이 완료되었습니다.
