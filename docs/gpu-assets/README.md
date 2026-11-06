# 교내 GPU(틸론)로 만든 이미지

교내 GPU(틸론) 주피터 환경에서 오픈소스 이미지 모델 **`stabilityai/sdxl-turbo`**로 만든 결과물입니다. 생성 기록은 [`manifest.json`](manifest.json)(모델, 분류, 크기), 전체 모아보기는 [`contact_sheet.png`](contact_sheet.png)입니다.

- 생성한 이미지: **16장** (브랜딩 2, 캐릭터 4, 아이템 5, 배경 4, 엔딩 1)
- 서비스에 적용한 파일(줄여서 웹용으로 변환): [`app/static/assets/`](../../app/static/assets/)
- 생성 기록에 GPU 종류, 프롬프트, 시드는 들어 있지 않습니다.

| 분류 | 이름 | 크기 | 파일 | 쓴 곳 |
| --- | --- | --- | --- | --- |
| branding | storyguard_emblem | 512×512 | `branding/storyguard_emblem.png` | 서비스 화면 로고·파비콘, 발표자료 표지 로고 |
| branding | lighthouse_title_art | 768×432 | `branding/lighthouse_title_art.png` | 서비스 화면 배경, 발표자료 표지 배경 |
| characters | protagonist | 512×512 | `characters/protagonist.png` | 발표자료 표지·고객 쪽 |
| characters | engineer | 512×512 | `characters/engineer.png` | 발표자료 해결 쪽(AI) |
| characters | archivist | 512×512 | `characters/archivist.png` | 발표자료 표지·해결 쪽(알고리즘) |
| characters | lighthouse_keeper | 512×512 | `characters/lighthouse_keeper.png` | 아직 쓰지 않음 |
| items | rusted_gear | 512×512 | `items/rusted_gear.png` | 아직 쓰지 않음 |
| items | brass_gear | 512×512 | `items/brass_gear.png` | 아직 쓰지 않음 |
| items | keeper_note | 512×512 | `items/keeper_note.png` | 아직 쓰지 않음 |
| items | lighthouse_key | 512×512 | `items/lighthouse_key.png` | 아직 쓰지 않음 |
| items | blue_glass | 512×512 | `items/blue_glass.png` | 아직 쓰지 않음 |
| backgrounds | harbor | 768×432 | `backgrounds/harbor.png` | 아직 쓰지 않음 |
| backgrounds | mist_forest | 768×432 | `backgrounds/mist_forest.png` | 발표자료 모든 쪽 머리 띠 |
| backgrounds | underground_workshop | 768×432 | `backgrounds/underground_workshop.png` | 아직 쓰지 않음 |
| backgrounds | lighthouse_control_room | 768×432 | `backgrounds/lighthouse_control_room.png` | 아직 쓰지 않음 |
| ending | beacon_ending | 768×432 | `ending/beacon_ending.png` | 발표자료 마지막 쪽 배너 |

생성 노트북에 대해: 이 저장소의 [`tools/gpu/storyguard_assets.ipynb`](../../tools/gpu/storyguard_assets.ipynb)는 준비해 둔 노트북이며, **위 이미지를 만든 노트북이 아닙니다**(실행한 적 없음). 위 이미지를 만든 노트북은 별도입니다.
