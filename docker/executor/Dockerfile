FROM python:3.10-slim

RUN useradd -m sandbox
USER sandbox

WORKDIR /sandbox

# Минимальный образ с Python для запуска кода.
# Дополнительные пакеты безопасности по требованию можно добавить позже.

CMD ["python", "-c", "print('Executor image is ready. Use it via backend API.')"]

