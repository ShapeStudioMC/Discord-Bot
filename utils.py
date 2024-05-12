import aiosqlite as sqlite


def convert_permission(permissions: str | dict) -> dict | str:
    """
    Convert a string of permissions to a dictionary of permissions with the key being the permission name and the value
    being the permission value.
    :param permissions: The string of permissions
    :return: A dictionary of permissions
    """
    if isinstance(permissions, str):
        perm_dict = {
            "manage_local_permissions": False,
            "manage_embeds": False
        }
        print(f"permissions: {permissions}")
        if permissions == "" or permissions is None:
            return perm_dict
        if "MNG_PERM" in permissions:
            perm_dict["manage_local_permissions"] = True
        if "MNG_EMB" in permissions:
            perm_dict["manage_embeds"] = True
        return perm_dict
    elif isinstance(permissions, dict):
        # Convert the dictionary to a string (for storing in the database)
        perm_string = ""
        if permissions["manage_local_permissions"]:
            perm_string += "MNG_PERM"
        if permissions["manage_embeds"]:
            perm_string += "MNG_EMB"
        return perm_string
    else:
        raise TypeError("Permissions must be a string or a dictionary")


async def has_permission(user_id: int, permission: str, database_location: str) -> bool:
    """
    Check if a user has a specific permission
    :param database_location: The location of the database
    :param user_id: The user ID to check
    :param permission: The permission to check
    :return: True if the user has the permission, False otherwise
    """
    async with sqlite.connect(database_location) as db:
        async with db.execute("SELECT permissions FROM users WHERE user_id = ?", (user_id,)) as cursor:
            permissions = await cursor.fetchone()
    permissions = convert_permission(permissions[0])
    return permissions[permission]
