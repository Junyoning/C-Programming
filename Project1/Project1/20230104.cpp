#include <stdio.h>
#include <math.h>

#define MAX_DATA_NO 100

double sonar_data[MAX_DATA_NO] = { -1, };
double sum;
double m; // 평균변수
double v; // 분산변수
double a; // 표준편차 변수

int i = 0;

int main(int argc, char* argv[])
{
	FILE* fp;

	int no_line = -1;
	int result;
	
	double temp;
	

	printf("HELLO, goorm!\n");

	//fp = fopen("/workspace/HL_Mando_SW/sonar_data.txt", "r");
	fp = fopen("sonar_data.txt", "r");

	if (fp == NULL)
	{
		printf("FILE DOES NOT EXIST\n");
	}
	else
	{
		do
		{
			result = fscanf(fp, "%lf", &temp);
			sonar_data[++no_line] = temp;
		} while (result != EOF);

		printf("no of line %d\n", no_line);

		//for(i = 0; i < no_line; i++)
		//{	
		//	printf("%lf\n", sonar_data[0]); // 받아오는지 확인
		//}
		for (i = 0; i < no_line; i++)
		{
			sum += sonar_data[i];
			m = sum / no_line;
			printf("평균 = %lf\n", m);
		}

		for (i = 0; i < no_line; i++)
		{
			sum += (sonar_data[i] - m) * (sonar_data[i] - m);
			v = sum / no_line;
			printf("분산 = %lf\n", v);
		}

		a = sqrt(v);
		printf("표준편차 = %lf\n", a);

	}
	return 0;
}
