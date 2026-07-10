import os
import logging
from datetime import datetime, time
import asyncio

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)
from notion_client import Client

# ─── Настройки ───────────────────────────────────────────────────────────────

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")
YOUR_CHAT_ID = int(os.environ.get("YOUR_CHAT_ID", "0"))

# Время отправки вопросов (UTC). Скопье = UTC+2, значит 21:00 UTC = 23:00 по Скопье
SEND_HOUR_UTC = 21
SEND_MINUTE_UTC = 0

notion = Client(auth=NOTION_TOKEN)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Вопросы дневника ────────────────────────────────────────────────────────

QUESTIONS = [
    ("события", "📅 *События дня.*\nЧто произошло сегодня? Чем занималась, где была, с кем виделась?"),
    ("оценка", "🌡 *Оценка дня.*\nОцени своё эмоциональное состояние от 1 до 9.\n_(просто напиши цифру)_"),
    ("радость", "🌸 *Радость дня.*\nЧто тебя сегодня порадовало? За что ты благодарна этому дню?"),
    ("сложный", "💭 *Сложный момент.*\nКакой момент дня был самым сложным и почему? Что тебя сейчас беспокоит?"),
    ("совет", "🤝 *Совет другу.*\nКакой совет ты бы дала подруге в твоей ситуации?"),
    ("желания", "✨ *Мои желания.*\nЧего бы ты хотела вместо этого? Или просто: «А что, если бы...»"),
    ("молодец", "🏆 *Я молодец.*\nЧто ты сегодня сделала — для дома, детей, дохода, себя?"),
    ("цели", "🎯 *Отслеживание целей.*\nЧто делала сегодня: медитация, заработок, вода, английский?"),
    ("тело", "💪 *Забота о себе.*\nЧто сделала сегодня для своего тела? (спорт, уход за собой)"),
    ("путешествия", "🗺 *Путешествия.*\nГде была? Какое новое место посетила? Что нового увидела?\n_(если нет — просто прочерк)_"),
    ("финансы", "💰 *Мои финансы.*\nСколько заработала сегодня и за что?"),
    ("саморазвитие", "📚 *Саморазвитие.*\nЧто читала или смотрела? Твои впечатления?"),
    ("еда", "🍽 *Питание.*\nЧто ела сегодня (и чем кормила семью)? Желательно со временем."),
    ("позитив", "💛 *Позитивный дневник.*\nЧто тебе нравится в... муже, месте где живёшь, в себе?"),
]

# Состояния разговора
(EVENTS, RATING, JOY, HARD, ADVICE, WISHES, PROUD, GOALS, BODY,
 TRAVEL, FINANCE, SELF_DEV, FOOD, POSITIVE) = range(14)

STATE_ORDER = [
    EVENTS, RATING, JOY, HARD, ADVICE, WISHES, PROUD, GOALS,
    BODY, TRAVEL, FINANCE, SELF_DEV, FOOD, POSITIVE
]

# Хранилище ответов (в памяти)
user_answers = {}

# ─── Сохранение в Notion ──────────────────────────────────────────────────────

def save_to_notion(answers: dict, date_str: str):
    rating = answers.get("оценка", "").strip()
    if rating not in [str(i) for i in range(1, 10)]:
        rating = "5"

    notion.pages.create(
        parent={"database_id": NOTION_DATABASE_ID},
        properties={
            "События дня. Что произошло сегодня? Чем занималась, где была, с кем виделась?": {
                "title": [{"text": {"content": answers.get("события", "—")}}]
            },
            "Оценка дня (эмоционального состояния)состояния": {
                "select": {"name": rating}
            },
            "Радость дня. Что меня сегодня порадовало? За что я благодарна этому дню?": {
                "rich_text": [{"text": {"content": answers.get("радость", "—")}}]
            },
            "Какой момент дня был самым сложным и почему? Что меня сейчас беспокоит и почему?": {
                "rich_text": [{"text": {"content": answers.get("сложный", "—")}}]
            },
            "Какой совет я бы дала другу в моей ситуации?": {
                "rich_text": [{"text": {"content": answers.get("совет", "—")}}]
            },
            "Мои желания. Чего я хотела бы вместо этого? Или просто было бы круто, если бы это произошло? \"А что, если...\" (или \"Вот было бы круто...\")": {
                "rich_text": [{"text": {"content": answers.get("желания", "—")}}]
            },
            "Я молодец. Что я сегодня сделала (для дома, детей, дохода, себя...)": {
                "rich_text": [{"text": {"content": answers.get("молодец", "—")}}]
            },
            "Отслеживание моих целей. Что я делала сегодня (медитация, заработок, вода, английский)": {
                "rich_text": [{"text": {"content": answers.get("цели", "—")}}]
            },
            "Что я сделал сегодня, чтобы позаботиться о себе и своем теле? (спорт и уход за собой)": {
                "rich_text": [{"text": {"content": answers.get("тело", "—")}}]
            },
            "Путешествия. Где я была? Какое новое место посетила? Что нового увидела? Описать подробнее впечатления (если нет, просто прочерк)": {
                "rich_text": [{"text": {"content": answers.get("путешествия", "—")}}]
            },
            "Мои финансы. Сколько я заработала за сегодня (и за что)?": {
                "rich_text": [{"text": {"content": answers.get("финансы", "—")}}]
            },
            "Саморазвитие. Что я читала или смотрела? Мои впечатления?": {
                "rich_text": [{"text": {"content": answers.get("саморазвитие", "—")}}]
            },
            "Что я сегодня ела (и чем кормила семью). И желательно время, если помню.": {
                "rich_text": [{"text": {"content": answers.get("еда", "—")}}]
            },
            "Позитивный дневник. Что мне нравится в... (муже; в детях; в месте, где я живу; в себе...)": {
                "rich_text": [{"text": {"content": answers.get("позитив", "—")}}]
            },
            "Date": {
                "date": {"start": date_str}
            },
        }
    )

# ─── Хендлеры разговора ───────────────────────────────────────────────────────

async def start_diary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_answers[chat_id] = {"дата": datetime.now().strftime("%Y-%m-%d")}
    key, question = QUESTIONS[0]
    await update.message.reply_text(
        f"🌙 *Время заполнить дневник!*\n\nВопрос 1 из {len(QUESTIONS)}:\n\n{question}",
        parse_mode="Markdown"
    )
    return EVENTS

async def handle_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_answers[chat_id]["события"] = update.message.text
    key, question = QUESTIONS[1]
    await update.message.reply_text(f"Вопрос 2 из {len(QUESTIONS)}:\n\n{question}", parse_mode="Markdown")
    return RATING

async def handle_rating(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_answers[chat_id]["оценка"] = update.message.text
    key, question = QUESTIONS[2]
    await update.message.reply_text(f"Вопрос 3 из {len(QUESTIONS)}:\n\n{question}", parse_mode="Markdown")
    return JOY

async def handle_joy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_answers[chat_id]["радость"] = update.message.text
    key, question = QUESTIONS[3]
    await update.message.reply_text(f"Вопрос 4 из {len(QUESTIONS)}:\n\n{question}", parse_mode="Markdown")
    return HARD

async def handle_hard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_answers[chat_id]["сложный"] = update.message.text
    key, question = QUESTIONS[4]
    await update.message.reply_text(f"Вопрос 5 из {len(QUESTIONS)}:\n\n{question}", parse_mode="Markdown")
    return ADVICE

async def handle_advice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_answers[chat_id]["совет"] = update.message.text
    key, question = QUESTIONS[5]
    await update.message.reply_text(f"Вопрос 6 из {len(QUESTIONS)}:\n\n{question}", parse_mode="Markdown")
    return WISHES

async def handle_wishes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_answers[chat_id]["желания"] = update.message.text
    key, question = QUESTIONS[6]
    await update.message.reply_text(f"Вопрос 7 из {len(QUESTIONS)}:\n\n{question}", parse_mode="Markdown")
    return PROUD

async def handle_proud(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_answers[chat_id]["молодец"] = update.message.text
    key, question = QUESTIONS[7]
    await update.message.reply_text(f"Вопрос 8 из {len(QUESTIONS)}:\n\n{question}", parse_mode="Markdown")
    return GOALS

async def handle_goals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_answers[chat_id]["цели"] = update.message.text
    key, question = QUESTIONS[8]
    await update.message.reply_text(f"Вопрос 9 из {len(QUESTIONS)}:\n\n{question}", parse_mode="Markdown")
    return BODY

async def handle_body(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_answers[chat_id]["тело"] = update.message.text
    key, question = QUESTIONS[9]
    await update.message.reply_text(f"Вопрос 10 из {len(QUESTIONS)}:\n\n{question}", parse_mode="Markdown")
    return TRAVEL

async def handle_travel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_answers[chat_id]["путешествия"] = update.message.text
    key, question = QUESTIONS[10]
    await update.message.reply_text(f"Вопрос 11 из {len(QUESTIONS)}:\n\n{question}", parse_mode="Markdown")
    return FINANCE

async def handle_finance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_answers[chat_id]["финансы"] = update.message.text
    key, question = QUESTIONS[11]
    await update.message.reply_text(f"Вопрос 12 из {len(QUESTIONS)}:\n\n{question}", parse_mode="Markdown")
    return SELF_DEV

async def handle_selfdev(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_answers[chat_id]["саморазвитие"] = update.message.text
    key, question = QUESTIONS[12]
    await update.message.reply_text(f"Вопрос 13 из {len(QUESTIONS)}:\n\n{question}", parse_mode="Markdown")
    return FOOD

async def handle_food(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_answers[chat_id]["еда"] = update.message.text
    key, question = QUESTIONS[13]
    await update.message.reply_text(f"Вопрос 14 из {len(QUESTIONS)}:\n\n{question}", parse_mode="Markdown")
    return POSITIVE

async def handle_positive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_answers[chat_id]["позитив"] = update.message.text

    await update.message.reply_text("⏳ Сохраняю в Notion...")

    try:
        answers = user_answers[chat_id]
        save_to_notion(answers, answers["дата"])
        await update.message.reply_text(
            "✅ *Дневник заполнен и сохранён в Notion!*\n\nСпокойной ночи 🌙",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка Notion: {e}")
        await update.message.reply_text(f"❌ Ошибка при сохранении в Notion: {e}")

    user_answers.pop(chat_id, None)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_answers.pop(chat_id, None)
    await update.message.reply_text("❌ Заполнение дневника отменено. Напиши /start чтобы начать заново.")
    return ConversationHandler.END

# ─── Ежедневная отправка по расписанию ───────────────────────────────────────

async def send_daily_prompt(context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=YOUR_CHAT_ID,
        text="🌙 *Время заполнить дневник!*\n\nНапиши /start чтобы начать.",
        parse_mode="Markdown"
    )

# ─── Запуск приложения ────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start_diary)],
        states={
            EVENTS:    [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_events)],
            RATING:    [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_rating)],
            JOY:       [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_joy)],
            HARD:      [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_hard)],
            ADVICE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_advice)],
            WISHES:    [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_wishes)],
            PROUD:     [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_proud)],
            GOALS:     [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_goals)],
            BODY:      [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_body)],
            TRAVEL:    [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_travel)],
            FINANCE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_finance)],
            SELF_DEV:  [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_selfdev)],
            FOOD:      [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_food)],
            POSITIVE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_positive)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)

    # Ежедневное расписание
    app.job_queue.run_daily(
        send_daily_prompt,
        time=time(hour=SEND_HOUR_UTC, minute=SEND_MINUTE_UTC),
    )

    logger.info("Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
