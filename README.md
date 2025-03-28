# Discord Bot for ShapeStudio

This is a Discord bot developed by BEMZlabs for ShapeStudio. The bot is designed to manage forum threads, notes, and embeds within a Discord server. It includes various commands and event listeners to facilitate these functionalities.

## Features

- **Forum Thread Management**: 
  - Create, update, and delete forum threads.
  - Close forum threads.
  - Assign and remove users from forum threads.
  - List all users assigned to a forum thread.
- **Note Management**: 
  - Add, edit, and delete notes for forum threads.
  - Change the default note for a forum channel.
  - Refresh notes for all forum threads.
- **Embed Management**: 
  - Create, edit, and delete embeds.
  - Show embeds.
- **Periodic Updates**: Automatically update notes for all threads every 5 minutes.
- **Permissions**: Manage permissions for different users.

## Requirements

- Python 3.8+
- Dependencies in `requirements.txt`

## Installation

1. Clone the repository:
    ```sh
    git clone https://github.com/ShapeStudioMC/Discord-Bot.git
    cd Discord-Bot
    ```

2. Create a virtual environment and activate it:
    ```sh
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```

3. Install the required dependencies:
    ```sh
    pip install -r requirements.txt
    ```

4. Create a `.env` file based on the `.env.example` file and fill in the required values:
    ```sh
    cp .env.example .env
    ```

5. Run the bot:
    ```sh
    python main.py
    ```

## Usage

### Commands

- **/forum setup**: Set up a channel as a forum channel to track.
- **/forum note**: Modify the note for a forum thread.
- **/forum default\_note**: Change the default note for a forum channel.
- **/forum update**: Update the note for all forum threads.
- **/forum close**: Close a forum thread.
- **/assign add**: Assign a user to a forum thread.
- **/assign remove**: Remove a user from a forum thread.
- **/assign list**: List all users assigned to a forum thread.
- **/embed create**: Create a new embed.
- **/embed show**: Show an embed.
- **/embed delete**: Delete an embed.
- **/embed edit**: Edit an embed.
- **/shard**: Get the shard ID and info for the current guild.

## License

This project is licensed under the GNU General Public License v2.0. See the [LICENSE](LICENSE) file for details.

## Contributing

1. Fork the repository.
2. Create a new branch (`git checkout -b feature-branch`).
3. Make your changes.
4. Commit your changes (`git commit -am 'Add new feature'`).
5. Push to the branch (`git push origin feature-branch`).
6. Create a new Pull Request.

## Contact

For any inquiries, please contact BEMZlabs at shapestudio.github@bemz.info.