#--------------------------------------------------------------------------------------------------------------
#--------------------------------------------------------------------------------------------------------------


import sys, os
if os.path.abspath("..") not in sys.path:
    sys.path.insert(0, os.path.abspath("../.."))
from fastapi import FastAPI, HTTPException, Request
import json
import socket
# import logging
import pn_utilities.logger.PnLogger as PnLogger
#---------------------------------------------------
# set the logging
#---------------------------------------------------
log=PnLogger.PnLogger()
#---------------------------------------------------
# load the crypto environment
#---------------------------------------------------
import pn_utilities.crypto.PnCrypto as PnCrypto

# config file will be taken from PN_CRYPTO_CONFIG_FILE
# in container it is config_fastapi_container.json
# in local mode defaulting to config.json = local mysql started.

crypto_obj = PnCrypto.PnCrypto(os.environ.get('PN_CRYPTO_CONFIG_FILE', 'config.json'))

#---------------------------------------------------
# here we go load the FastAPI
#---------------------------------------------------

app = FastAPI()

#---------------------------------------------------------
# the get index .. root
#---------------------------------------------------------
@app.get("/")
async def root():
    log.info("in root")
    return {"message": "Hello from my World"}

#---------------------------------------------------------
# the get keys list all keys
#---------------------------------------------------------
@app.get("/v1/keys")
async def v1_keys():
    log.info("get keys")
    keys = crypto_obj.get_PnCryptoKeys();
    r_msg = keys.get_keys_json()
    return {r_msg}

#---------------------------------------------------------
# the get a key 
#---------------------------------------------------------
@app.get("/v1/keys/{id}")
async def v1_get_key(id: str):
    log.info("get key called with parameter id:" + id)
    keys = crypto_obj.get_PnCryptoKeys();
    r_msg = keys.get_key_json(id)
    return {r_msg}

#---------------------------------------------------------
# the delete a key 
#---------------------------------------------------------
@app.delete("/v1/keys/{id}")
def delete_key(id: str):
    log.info("delete key called with parameter id:" + id)
    keys = crypto_obj.get_PnCryptoKeys();
    keys.delete_key(id)
    return {"ok": True}
#---------------------------------------------------------
# the post a key 
#---------------------------------------------------------
# @app.route('/v1/keys 
@app.post("/v1/keys", status_code=201)
async def v1_post_key(request: Request):
    log.info("post key called")
    try:
        # Extracting user data from the request body
        data_json = await request.json()
        keys = crypto_obj.get_PnCryptoKeys();

        # Validate the presence of required fields
        log.info("Request received" + data_json)
        if 'id' not in data_json or 'value' not in data_json:
            raise HTTPException(
                status_code=422, detail='Incomplete data provided')

        # parse the dato with json loads and extract f002 and f049
        data = json.loads(data_json)
        
        id = data['id']
        description = data['description']
        value = data['value']
        type = data['type']
        
        if (keys.import_key(id, description, value, type) == True):
            return {"ok": True}
        else:
            raise HTTPException(
                status_code=422, detail='Key already exists')

    except HTTPException as e:
        # Re-raise HTTPException to return the specified status code and detail
        raise e
    except Exception as e:
        # Handle other unexpected exceptions and return a 500 Internal Server Error
        raise HTTPException(
            status_code=500, detail='An error occurred: {str(e)}')

#-------------------------------------------------------------------------
# post /v1/arqc:  handling request arqc calculate an arqc
#-------------------------------------------------------------------------
@app.post("/v1/arqc")
async def v1_arqc(request: Request):
    hostname = socket.gethostname()
 
    try:
        # Extracting user data from the request body
        data_json = await request.json()
        # Validate the presence of required fields
        log.info("Request received" + data_json)
        if 'pan' not in data_json or 'psn' not in data_json:
            raise HTTPException(
                status_code=422, detail='Incomplete data provided')

        # parse the dato with json loads and extract f002 and f049
        data = json.loads(data_json)
        
        key_name = data['key_name']
        pan = data['pan']
        psn = data['psn']
        atc = data['atc']
        data = data['data']
        ret_message['host'] = hostname
        ret_message['arqc'] = crypto_obj.do_arqc(key_name, pan, psn, atc, data, True)
        log.info(ret_message)
        return {ret_message}

    except HTTPException as e:
        # Re-raise HTTPException to return the specified status code and detail
        raise e
    except Exception as e:
        # Handle other unexpected exceptions and return a 500 Internal Server Error
        raise HTTPException(
            status_code=500, detail='An error occurred: {str(e)}')
#-------------------------------------------------------------------------
# post /v1/arpc:  handling request arpc calculate an arpc
#-------------------------------------------------------------------------
@app.post("/v1/arpc")
async def v1_arpc(request: Request):
    hostname = socket.gethostname()
 
    try:
        # Extracting user data from the request body
        data_json = await request.json()
        # Validate the presence of required fields
        log.info("Request received" + data_json)
        if 'pan' not in data_json or 'psn' not in data_json:
            raise HTTPException(
                status_code=422, detail='Incomplete data provided')

        # parse the dato with json loads and extract f002 and f049
        data = json.loads(data_json)
        
        key_name = data['key_name']
        pan = data['pan']
        psn = data['psn']
        atc = data['atc']
        csu = data['csu']
        arqc = data['arqc']
        ret_message['host'] = hostname
        ret_message['arpc'] = crypto_obj.do_arpc(key_name, pan, psn, atc, arqc, csu)
        # Returning a confirmation message
        log.info(ret_message)
        return {'message': ret_message}

    except HTTPException as e:
        # Re-raise HTTPException to return the specified status code and detail
        raise e
    except Exception as e:
        # Handle other unexpected exceptions and return a 500 Internal Server Error
        raise HTTPException(
            status_code=500, detail='An error occurred: {str(e)}')


#-------------------------------------------------------------------------
# post transcode_0100:  handling request type 0100
#-------------------------------------------------------------------------
@app.post("/transcode_0100")
async def add_transcode_0100(request: Request):
    hostname = socket.gethostname()
 
    try:
        # Extracting user data from the request body
        data_json = await request.json()
        # Validate the presence of required fields
        log.info("Request received" + data_json)
        if 'f002' not in data_json or 'f049' not in data_json:
            raise HTTPException(
                status_code=422, detail='Incomplete data provided')

        # parse the dato with json loads and extract f002 and f049
        data = json.loads(data_json)
        
        pan = data['f002']
        cur = data['f049']

        # Returning a confirmation message
        ret_message = 'host:' + hostname + ': pan and key submitted updated successfully pan:' + pan + ' cur:' + cur
        log.info(ret_message)
        return {'message': ret_message}

    except HTTPException as e:
        # Re-raise HTTPException to return the specified 
        # status code and detail
        print("here")
        raise e
    except Exception as e:
        # Handle other unexpected exceptions and return a 
        # 500 Internal Server Error
        print("ehre two")
        raise HTTPException(
            status_code=500, detail='An error occurred: {str(e)}')


#-----------------------------------------------------------
# we can run it from here or with fastapi dev main.py
#-----------------------------------------------------------
if __name__ == '__main__':
    import uvicorn
    # Run the FastAPI application using uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8080)

