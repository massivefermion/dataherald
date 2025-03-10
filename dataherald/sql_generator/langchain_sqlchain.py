"""A wrapper for the SQL generation functions in langchain"""

import logging
import time
from typing import List

from langchain import SQLDatabaseChain
from langchain.callbacks import get_openai_callback
from overrides import override

from dataherald.sql_database.base import SQLDatabase
from dataherald.sql_database.models.types import DatabaseConnection
from dataherald.sql_generator import SQLGenerator
from dataherald.types import NLQuery, NLQueryResponse

logger = logging.getLogger(__name__)

PROMPT_WITHOUT_CONTEXT = """
Given an input question,
first create a syntactically correct postgresql query to run,
then look at the results of the query and return the answer.

The question:
{user_question}
"""

PROMPT_WITH_CONTEXT = """
Given an input question,
first create a syntactically correct postgresql query to run,
then look at the results of the query and return the answer.

An example of a similar question and the query that was generated to answer it is the following
{context}

The question:
{user_question}
"""


class LangChainSQLChainSQLGenerator(SQLGenerator):
    @override
    def generate_response(
        self,
        user_question: NLQuery,
        database_connection: DatabaseConnection,
        context: List[dict] = None,
    ) -> NLQueryResponse:
        start_time = time.time()
        self.database = SQLDatabase.get_sql_engine(database_connection)
        logger.info(
            f"Generating SQL response to question: {str(user_question.dict())} with passed context {context}"
        )
        if context is not None:
            samples_prompt_string = "The following are some similar previous questions and their correct SQL queries from these databases: \
            \n"
            for sample in context:
                samples_prompt_string += (
                    f"Question: {sample['nl_question']} \nSQL: {sample['sql_query']} \n"
                )

            prompt = PROMPT_WITH_CONTEXT.format(
                user_question=user_question.question, context=samples_prompt_string
            )
        else:
            prompt = PROMPT_WITHOUT_CONTEXT.format(user_question=user_question.question)
        # should top_k be an argument?
        db_chain = SQLDatabaseChain.from_llm(
            self.llm, self.database, top_k=3, return_intermediate_steps=True
        )
        with get_openai_callback() as cb:
            result = db_chain(prompt)

        intermediate_steps = []
        for step in result["intermediate_steps"]:
            intermediate_steps.append(str(step))
        exec_time = time.time() - start_time
        logger.info(
            f"cost: {str(cb.total_cost)} tokens: {str(cb.total_tokens)} time: {str(exec_time)}"
        )
        response = NLQueryResponse(
            nl_question_id=user_question.id,
            nl_response=result["result"],
            intermediate_steps=intermediate_steps,
            exec_time=exec_time,
            total_cost=cb.total_cost,
            total_tokens=cb.total_tokens,
            sql_query=result["intermediate_steps"][1],
        )
        return self.create_sql_query_status(self.database, response.sql_query, response)
