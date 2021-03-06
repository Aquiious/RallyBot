"""
Registration/Onboarding interface, user provides GW2 API key and answers
the onboarding questions, which provides the info we need for some of the
bot's functionality.
"""
import discord
import aiohttp
import asyncio
import boto3
import gw2Api

#Components
import util

db = util.getDB()
members = db.Table('members')

#Advances the registration step for the given id by 1
def advanceStep(discordID):

    #get current step value
    response = members.get_item(
        Key = {
            'id' : discordID
        }
    )

    #Advance step by 1
    registrationStep = response['Item']['registrationStep']
    registrationStep += 1

    #Store back in database
    members.update_item(
        Key = {
            'id' : discordID
        },
        UpdateExpression = 'set registrationStep = :in_registrationStep',
        ExpressionAttributeValues = {
            ':in_registrationStep' : registrationStep
        }
    )


#Takes the provided api key, grabs data from it and saves to the db
async def apiStep(discordID, apiKey):

    ###########################################
    ##Make request from API
    ###########################################

    #Parallelize request for increased performance
    async with aiohttp.ClientSession() as session:

        #Make request for character names and account info
        tasks = []
        tasks.append(gw2Api.getCharacterNames(apiKey, session))
        tasks.append(gw2Api.getAccountInfo(apiKey, session))
        response = await asyncio.gather(*tasks)

        #Retrieve list of characters
        res = response[0]
        characterList = res['body']
        #Bad API Key
        if(res['status'] != 200):
            return ('Problem using API Key: \'%s\'\nPlease respond with a valid GW2 API\
            key with account, characters, builds and progression information.' %(res['body']['text']))


        #Retrieve account info
        res = response[1]
        #Bad request
        if(not res['status']):
            return ('Problem using API Key: \'%s\'' %(res['body']['text']))
        #Extract account info
        acctInfo = res['body']


        #Retrieve character and server info
        tasks = [gw2Api.getServer(acctInfo['world'], session)]
        for character in characterList:
            tasks.append(gw2Api.getCharacterInfo(apiKey, character, session))
        response = await asyncio.gather(*tasks)


        #Extract Server Info
        res = response[0]
        #bad request
        if(not res['status']):
            return ('Problem using API Key: \'%s\'' %(res['body']['text']))
        server = res['body'][0]['name']

        response.pop(0)#pop the world info, leaving just character info

        #Extract character info for each character
        characters = {}
        for res in response:
            if(not res['status']):
                return ('Problem using API Key: \'%s\'' %(res['body']['text']))
            cInfo = res['body']
            characters[cInfo['name']] = cInfo['profession']

    ###########################################
    ##Store in database
    ###########################################

    members.update_item(
        Key = {
            'id' : discordID
        },
        UpdateExpression = 'set characters = :in_characters, acctName = :in_acctName, server = :in_server',
        ExpressionAttributeValues = {
            ':in_characters' : characters,
            ':in_acctName' : acctInfo['name'],
            ':in_server' : server
        }
    )

    advanceStep(discordID)
    retVal = 'API Successfully Verified!\nPlease select your main from the list of characters below:\n'
    retVal += util.charactersToString(characters)
    retVal += 'Respond with the name of your selection.'
    return retVal


async def setMainStep(discordID, selection):

    #Get member information
    response = members.get_item(
        Key = {
            'id' : discordID
        }
    )

    characters = response['Item']['characters']

    #Check if the selection is actually an int
    if(not selection in characters):
        retVal = 'Selection not found!\nPlease respond with the name of your main character from the list below:\n'
        retVal += util.charactersToString(characters)
        return retVal
    
    #Set main
    members.update_item(
        Key = {
            'id' : discordID
        },
        UpdateExpression = 'set mainCharacter = :in_mainCharacter',
        ExpressionAttributeValues = {
            ':in_mainCharacter' : selection,
        }
    )

    advanceStep(discordID)
    util.deleteSession(discordID)
    return ('%s Selected\nRegistration Complete!' % (selection))

#Register the user, occurs in multiple steps
async def registrationSwitch(message):

    #Retrieve registrant info from the database
    discordID = message.author.id
    response = members.get_item(
        Key = {
            'id' : discordID
        }
    )

    registrationStep = 0
    info = None

    #Check if registrant is already in database
    if( 'Item' in response):
        #They are in database, grab their info and their registration step
        info = response['Item']
        registrationStep = info['registrationStep']
    else:
        #Not in database, add them as initial step
        members.update_item(
            Key = {
                'id' : discordID
            },
            UpdateExpression = 'set registrationStep = :in_registrationStep, discordName = :in_discordName',
            ExpressionAttributeValues = {
                ':in_registrationStep' : registrationStep,
                ':in_discordName' : str(message.author)
            }
        )

    #Registration Steps
    description = ''
    if(registrationStep == 0):
        #initial step, display instructions
        description = 'Welcome to EK Discord! We require an API key to register, which\
             we use to retrieve account/character names, guild status, home world and build info.\
            \nThe API does not provide us with sensitive information such as real name, email address,\
             or passwords.\
            \nPlease direct message this bot your API key with access to account, characters, builds and\
             progression to continue registration....'
        advanceStep(discordID)

    elif(registrationStep == 1):
        #API step, save api key and character info
        description = await apiStep(discordID, message.content)

    elif(registrationStep == 2):
        description = await setMainStep(discordID, message.content)

    elif(registrationStep == 3):
        description = 'Registration already completed!'
        util.deleteSession(discordID)



    #Retval Creation
    embed=discord.Embed(title = 'Registration Step %d of 2' % (registrationStep),
        description = description, color = 0x00ff00)

    return embed

