import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler, CallbackQueryHandler
)
import sqlite3

# Enable logging to see what's happening
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Database Setup ---
conn = sqlite3.connect('sections_bot.db', check_same_thread=False)
db = conn.cursor()
# Create a better table structure
db.execute('''CREATE TABLE IF NOT EXISTS sections
             (user_id INTEGER, section_name TEXT)''')
db.execute('''CREATE TABLE IF NOT EXISTS saved_items
             (user_id INTEGER, section_name TEXT, item_name TEXT, message_data TEXT)''')
conn.commit()

# --- Conversation States ---
GETTING_NAME, GETTING_SECTION = range(2)

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to your personal message saver!\n\n"
        "**How to use me:**\n"
        "1. Forward a message to me, or\n"
        "2. Send me a direct link to a message.\n"
        "I'll then ask you for a name and a section to save it in.\n\n"
        "**Commands:**\n"
        "/newsection <name> - Create a new section (e.g., '/newsection Recipes')\n"
        "/mysections - List all your sections",
        parse_mode='Markdown'
    )
    return ConversationHandler.END

# Command to create a new section
async def new_section(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Please provide a section name. Example: `/newsection Recipes`", parse_mode='Markdown')
        return
    section_name = " ".join(context.args)
    user_id = update.effective_user.id

    # Check if section already exists for this user
    db.execute("SELECT 1 FROM sections WHERE user_id=? AND section_name=?", (user_id, section_name))
    if db.fetchone():
        await update.message.reply_text(f"Section '{section_name}' already exists!")
        return

    # Save the new section to the database
    db.execute("INSERT INTO sections (user_id, section_name) VALUES (?, ?)", (user_id, section_name))
    conn.commit()
    await update.message.reply_text(f'✅ Section "{section_name}" created successfully!')

# Command to list user's sections
async def my_sections(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db.execute("SELECT section_name FROM sections WHERE user_id=?", (user_id,))
    sections = [row[0] for row in db.fetchall()]

    if not sections:
        await update.message.reply_text("You don't have any sections yet! Create one with `/newsection`", parse_mode='Markdown')
        return

    section_list = "\n".join([f"• {name}" for name in sections])
    await update.message.reply_text(f"**Your Sections:**\n{section_list}", parse_mode='Markdown')

# Handle incoming messages: Links and forwarded messages
async def handle_incoming(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message = update.message

    # Check if it's a message link
    if message.text and any(entity.type == "url" for entity in message.entities):
        context.user_data['message_data_to_save'] = message.text
        await update.message.reply_text("🔗 Great! What name would you like to give to this saved item?")
        return GETTING_NAME

    # Check if it's a forwarded message
    elif message.forward_date:
        # Store basic info about the forwarded message
        source = ""
        if message.forward_from_chat:
            source = f"from {message.forward_from_chat.title}"
        elif message.forward_from:
            source = f"from {message.forward_from.first_name}"

        context.user_data['message_data_to_save'] = f"Forwarded {source}: {message.text or '(media message)'}"
        await update.message.reply_text("📩 Great! What name would you like to give to this saved item?")
        return GETTING_NAME

    else:
        # If it's just text, ignore it or help the user
        await update.message.reply_text("Please forward a message to me or send me a direct message link to save it.")
        return ConversationHandler.END

# After user provides the name, ask for the section
async def get_item_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    item_name = update.message.text
    context.user_data['item_name_to_save'] = item_name
    user_id = update.effective_user.id

    # Fetch the user's existing sections from the database
    db.execute("SELECT section_name FROM sections WHERE user_id=?", (user_id,))
    sections = [row[0] for row in db.fetchall()]

    if not sections:
        await update.message.reply_text("You don't have any sections yet! Create one with `/newsection` first.", parse_mode='Markdown')
        return ConversationHandler.END

    # Create an inline keyboard with the sections
    keyboard = []
    for section in sections:
        keyboard.append([InlineKeyboardButton(section, callback_data=f"section_{section}")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"✏️ Name '{item_name}' saved. Now, choose a section:",
        reply_markup=reply_markup
    )
    return GETTING_SECTION

# Handle the user's section choice
async def handle_section_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chosen_section = query.data.replace('section_', '')
    user_id = query.from_user.id

    # Get the data we stored temporarily
    item_name = context.user_data.get('item_name_to_save')
    message_data = context.user_data.get('message_data_to_save')

    # Save everything to the database
    db.execute("INSERT INTO saved_items (user_id, section_name, item_name, message_data) VALUES (?, ?, ?, ?)",
               (user_id, chosen_section, item_name, message_data))
    conn.commit()

    # Clean up the temporary data
    context.user_data.pop('item_name_to_save', None)
    context.user_data.pop('message_data_to_save', None)

    await query.edit_message_text(
        text=f"✅ Perfect! I've saved '{item_name}' in the section '{chosen_section}'."
    )
    return ConversationHandler.END

# Cancel command
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Operation cancelled.')
    context.user_data.clear()
    return ConversationHandler.END

# Error handler
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception while handling an update:", exc_info=context.error)
    try:
        await update.message.reply_text("Sorry, something went wrong. Please try again.")
    except:
        pass

def main():
    # Get token from environment variable (important for Render)
    TOKEN = "7432768639:AAHhF4k7juq1YqT67IdNK3sa1QmaJ7lVvpY"  # We'll change this later for production

    # Create the Application
    application = Application.builder().token(TOKEN).build()

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("newsection", new_section))
    application.add_handler(CommandHandler("mysections", my_sections))
    application.add_handler(CommandHandler("cancel", cancel))

    # Set up the conversation handler for the core saving workflow
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.ALL & ~filters.COMMAND, handle_incoming)],
        states={
            GETTING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_item_name)],
            GETTING_SECTION: [CallbackQueryHandler(handle_section_choice)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    application.add_handler(conv_handler)

    # Add error handler
    application.add_error_handler(error_handler)

    # Start the bot
    print("Bot is starting...")
    application.run_polling()

if __name__ == '__main__':
    main()