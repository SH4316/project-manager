# notes 앱은 admin에 등록하지 않는다. MeetingNote도 Task·Project처럼 version 낙관적 잠금과
# services.py를 거치므로, admin 변경 폼을 열면 그 규칙을 조용히 어긴다(GUIDE-00 §3 참고).
