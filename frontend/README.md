# Poker AI Coach Frontend

Next.js frontend for testing the Texas Hold'em hand flow.

## Run

Start the backend first from `../backend`:

```bash
uvicorn app.main:app --reload
```

Then run the frontend:

```bash
npm install
npm run dev
```

The app uses `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000` by default.

### Языки интерфейса

Переключатель вверху страницы поддерживает русский и украинский языки. Выбор сохраняется в этом браузере и синхронизируется между вкладками. Смена языка не перезапускает раздачу и не переподключает комнату.

Переводы находятся в `i18n/messages.json`. API, действия и сохранённые записи используют прежние идентификаторы; старые англоязычные советы переводятся при отображении. Новые шаблоны текстов сервера следует добавлять в каталог переводов. Проверка каталога и динамических пояснений: `npm run test:i18n`.
