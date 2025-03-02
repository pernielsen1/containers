# https://www.geeksforgeeks.org/post-query-parameters-in-fastapi/
# select virtual env press ctrl-shift-p  then python:select interpretator
# stop start container will reload directly from this app i.e. not necessariy to build
from fastapi import FastAPI, HTTPException, Request
import json

app = FastAPI()

#---------------------------------------------------------
# the get index .. root
#---------------------------------------------------------
@app.get("/")
async def root():
    return {"message": "Hello from my World"}

#-------------------------------------------------------------------------
# post transcode_0100:  handling request type 0100
#-------------------------------------------------------------------------
@app.post("/transcode_0100")
async def add_transcode_0100(request: Request):
    try:
        # Extracting user data from the request body
        data_json = await request.json()

        # Validate the presence of required fields
        if 'f002' not in data_json or 'f049' not in data_json:
            raise HTTPException(
                status_code=422, detail='Incomplete data provided')

        # parse the dato with json loads and extract f002 and f049
        data = json.loads(data_json)
        
        pan = data['f002']
        cur = data['f049']

        # Returning a confirmation message
        ret_message = 'pan and key submitted updated successfully pan:' + pan + ' cur:' + cur
        return {'message': ret_message}

    except HTTPException as e:
        # Re-raise HTTPException to return the specified 
        # status code and detail
        raise e
    except Exception as e:
        # Handle other unexpected exceptions and return a 
        # 500 Internal Server Error
        raise HTTPException(
            status_code=500, detail='An error occurred: {str(e)}')

#-----------------------------------------------------------
# we can run it from here or with fastapi dev main.py
#-----------------------------------------------------------
if __name__ == '__main__':
    import uvicorn
    # Run the FastAPI application using uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8000)

